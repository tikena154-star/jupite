"""
JUPITE v3 — Application de rencontres
Nouveautés :
  - Page CGU/Avertissement avant inscription (18+ hommes uniquement)
  - Modération automatique des messages (numéros, redirections, liens)
  - Géolocalisation avec distance
  - Système de pièces (200 gratuits, -40/message)
  - Paiement multi-devises avec réduction CFA 50%
  - PWA installable (Play Store)
  - Compatible Render et Railway
"""

import os, json, math, uuid, re
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'jupite-secret-v3-2024-xK9mP')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///jupite.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ══════════════════════════════════════════════
#  CONSTANTES
# ══════════════════════════════════════════════

PIECES_INSCRIPTION = 200
COUT_PAR_MESSAGE   = 40
REDUCTION_CFA      = 0.50

OFFRES = [
    {'id':0,'pieces':480,   'usd':1.00,  'label':'Starter', 'badge':''},
    {'id':1,'pieces':1000,  'usd':2.00,  'label':'Basic',   'badge':''},
    {'id':2,'pieces':1500,  'usd':3.00,  'label':'Standard','badge':'🔥'},
    {'id':3,'pieces':3000,  'usd':4.10,  'label':'Premium', 'badge':'⭐'},
    {'id':4,'pieces':10000, 'usd':13.66, 'label':'Gold',    'badge':'👑'},
    {'id':5,'pieces':100000,'usd':140.30,'label':'Diamant',  'badge':'💎'},
]

PAYS_CFA = {
    'BJ','BF','CI','GW','ML','NE','SN','TG',
    'CM','CF','TD','CG','GQ','GA',
}
DEVISES_CFA = {'XOF','XAF','FCFA'}

TAUX = {
    'USD':1.0,'EUR':0.92,'GBP':0.79,'XOF':615.0,'XAF':615.0,
    'NGN':1580.0,'GHS':15.8,'KES':131.0,'ZAR':18.6,'EGP':30.9,
    'MAD':10.0,'DZD':134.5,'TND':3.12,'CAD':1.37,'CHF':0.89,
    'JPY':149.5,'CNY':7.24,'INR':83.1,'BRL':4.97,'MXN':17.2,
    'TRY':31.5,'RUB':91.0,'AED':3.67,'SAR':3.75,'QAR':3.64,
}
SYMBOLES = {
    'USD':'$','EUR':'€','GBP':'£','XOF':'FCFA','XAF':'FCFA',
    'NGN':'₦','GHS':'GH₵','KES':'KSh','ZAR':'R','EGP':'E£',
    'MAD':'MAD','DZD':'DA','TND':'DT','CAD':'CA$','CHF':'CHF',
    'JPY':'¥','CNY':'¥','INR':'₹','BRL':'R$','MXN':'MX$',
    'TRY':'₺','RUB':'₽','AED':'د.إ','SAR':'﷼','QAR':'﷼',
}

# ══════════════════════════════════════════════
#  MODÉRATION DES MESSAGES
# ══════════════════════════════════════════════

# Patterns de numéros de téléphone (international)
PATTERNS_TELEPHONE = [
    r'\b\d{8,}\b',                          # 8+ chiffres consécutifs
    r'\b\+\d{1,3}[\s\-]?\d{6,}\b',         # +225 07...
    r'\b0[0-9]{7,}\b',                      # 07 xx xx xx xx
    r'\b\d{2}[\s\.\-]\d{2}[\s\.\-]\d{2}',  # 07 xx xx xx
    r'\b\d{3}[\s\.\-]\d{3}[\s\.\-]\d{4}',  # 123-456-7890
]

# Mots et patterns de redirection externe
PATTERNS_REDIRECTION = [
    r'whatsapp', r'watsapp', r'wa\.me', r'whats[\s\-]?app',
    r'telegram', r't\.me', r'tg[\s\-]?:',
    r'instagram', r'insta[\s\-]?gram', r'@[a-zA-Z0-9_]{2,}',
    r'snapchat', r'snap[\s\-]?chat',
    r'facebook', r'fb\.com', r'fb[\s\-]?messenger',
    r'tiktok', r'tik[\s\-]?tok',
    r'twitter', r'x\.com',
    r'https?://', r'www\.', r'\.com', r'\.net', r'\.org',
    r'rejoins[\s\-]?moi', r'rejoignez[\s\-]?moi',
    r'contact[\s\-]?moi', r'contacte[\s\-]?moi',
    r'appelle[\s\-]?moi', r'appele[\s\-]?moi',
    r'mon[\s\-]?num[eé]ro', r'mon[\s\-]?tel',
    r'mon[\s\-]?numéro', r'voici[\s\-]?mon',
    r'envoie[\s\-]?moi', r'envoyer[\s\-]?moi',
    r'mail[\s\-]?moi', r'email[\s\-]?moi',
    r'écris[\s\-]?moi[\s\-]?sur', r'écris[\s\-]?sur',
    r'trouve[\s\-]?moi[\s\-]?sur',
    r'ajoute[\s\-]?moi',r'add[\s\-]?me',
]

# Mots grossiers / inappropriés
MOTS_INTERDITS = [
    'arnaque','spam','scam','pornographie','sexe explicite',
    'prostitution','drogue','cocaine','heroine','deal',
]

def analyser_message(texte):
    """
    Analyse un message et retourne :
    - (True, raison) si le message doit être bloqué
    - (False, None) si le message est autorisé
    """
    texte_lower = texte.lower().strip()

    # Vérifier numéros de téléphone
    for pattern in PATTERNS_TELEPHONE:
        if re.search(pattern, texte):
            return True, "numéro_téléphone"

    # Vérifier redirections externes
    for pattern in PATTERNS_REDIRECTION:
        if re.search(pattern, texte_lower):
            return True, "redirection_externe"

    # Vérifier mots interdits
    for mot in MOTS_INTERDITS:
        if mot in texte_lower:
            return True, "contenu_inapproprié"

    return False, None


# ══════════════════════════════════════════════
#  MODÈLES
# ══════════════════════════════════════════════

class User(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    uuid       = db.Column(db.String(36), unique=True, default=lambda: str(uuid.uuid4()))
    username   = db.Column(db.String(50), unique=True, nullable=False)
    email      = db.Column(db.String(120), unique=True, nullable=False)
    password   = db.Column(db.String(200), nullable=False)
    prenom     = db.Column(db.String(50))
    age        = db.Column(db.Integer)
    sexe       = db.Column(db.String(10))
    ville      = db.Column(db.String(100))
    pays       = db.Column(db.String(5), default='FR')
    devise     = db.Column(db.String(5), default='USD')
    lat        = db.Column(db.Float)
    lng        = db.Column(db.Float)
    bio        = db.Column(db.Text)
    interets   = db.Column(db.String(500))
    recherche  = db.Column(db.String(20))
    age_min    = db.Column(db.Integer, default=18)
    age_max    = db.Column(db.Integer, default=99)
    pieces     = db.Column(db.Integer, default=PIECES_INSCRIPTION)
    pieces_total_achete = db.Column(db.Integer, default=0)
    premium    = db.Column(db.Boolean, default=False)
    actif      = db.Column(db.Boolean, default=True)
    cgu_accepte = db.Column(db.Boolean, default=False)
    messages_bloques = db.Column(db.Integer, default=0)
    date_inscription   = db.Column(db.DateTime, default=datetime.utcnow)
    derniere_connexion = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def est_cfa(self):
        return self.pays in PAYS_CFA or self.devise in DEVISES_CFA

    def to_dict(self, dist=None):
        d = {
            'id':self.id,'username':self.username,'prenom':self.prenom,
            'age':self.age,'sexe':self.sexe,'ville':self.ville,
            'pays':self.pays,'devise':self.devise,'bio':self.bio,
            'interets':json.loads(self.interets) if self.interets else [],
            'premium':self.premium,'pieces':self.pieces,
            'lat':self.lat,'lng':self.lng,
            'symbole':SYMBOLES.get(self.devise, self.devise),
        }
        if dist is not None:
            d['distance_km'] = dist
        return d


class Like(db.Model):
    id        = db.Column(db.Integer, primary_key=True)
    from_user = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    to_user   = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date      = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('from_user','to_user'),)


class Match(db.Model):
    id       = db.Column(db.Integer, primary_key=True)
    user1_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user2_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date     = db.Column(db.DateTime, default=datetime.utcnow)
    actif    = db.Column(db.Boolean, default=True)


class Message(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    match_id   = db.Column(db.Integer, db.ForeignKey('match.id'), nullable=False)
    expediteur = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    contenu    = db.Column(db.Text, nullable=False)
    lu         = db.Column(db.Boolean, default=False)
    pieces_cout = db.Column(db.Integer, default=COUT_PAR_MESSAGE)
    bloque     = db.Column(db.Boolean, default=False)
    raison_blocage = db.Column(db.String(50))
    date       = db.Column(db.DateTime, default=datetime.utcnow)


class MessageBloque(db.Model):
    """Historique des messages bloqués pour audit."""
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    contenu    = db.Column(db.Text)
    raison     = db.Column(db.String(50))
    date       = db.Column(db.DateTime, default=datetime.utcnow)


class Transaction(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    user_id       = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    pieces        = db.Column(db.Integer, nullable=False)
    montant_usd   = db.Column(db.Float)
    montant_local = db.Column(db.Float)
    devise        = db.Column(db.String(5))
    symbole       = db.Column(db.String(6))
    moyen         = db.Column(db.String(20))
    reduction_cfa = db.Column(db.Boolean, default=False)
    reference     = db.Column(db.String(30))
    statut        = db.Column(db.String(20), default='simule')
    date          = db.Column(db.DateTime, default=datetime.utcnow)


# ══════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════

def current_user():
    uid = session.get('user_id')
    return User.query.get(uid) if uid else None

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user():
            if request.is_json:
                return jsonify({'success':False,'code':'AUTH_REQUIRED'}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def haversine(lat1, lng1, lat2, lng2):
    if None in (lat1, lng1, lat2, lng2):
        return None
    R = 6371
    p1,p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2-lat1)
    dl = math.radians(lng2-lng1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return round(R*2*math.atan2(math.sqrt(a), math.sqrt(1-a)), 1)

def prix_offre(idx, devise, est_cfa):
    offre = OFFRES[idx]
    usd = offre['usd'] * (1-REDUCTION_CFA if est_cfa else 1)
    taux = TAUX.get(devise, 1.0)
    local = usd * taux
    local = int(local) if taux >= 10 else round(local, 2)
    return {
        **offre,
        'usd_final': round(usd, 2),
        'prix_local': local,
        'devise': devise,
        'symbole': SYMBOLES.get(devise, devise),
        'reduction': est_cfa,
        'economie_pct': 50 if est_cfa else 0,
    }

def find_match(u1, u2):
    return Match.query.filter(
        ((Match.user1_id==u1)&(Match.user2_id==u2))|
        ((Match.user1_id==u2)&(Match.user2_id==u1))
    ).first()


# ══════════════════════════════════════════════
#  PAGES HTML
# ══════════════════════════════════════════════

@app.route('/')
def index():
    return redirect(url_for('discover')) if current_user() else render_template('index.html')

@app.route('/cgu')
def cgu():
    return render_template('cgu.html')

@app.route('/inscription')
def inscription_page():
    return render_template('inscription.html')

@app.route('/connexion')
def login():
    return render_template('login.html')

@app.route('/decouvrir')
@login_required
def discover():
    return render_template('discover.html')

@app.route('/matches')
@login_required
def matches():
    return render_template('matches.html')

@app.route('/messages/<int:match_id>')
@login_required
def messages(match_id):
    m = Match.query.get_or_404(match_id)
    me = current_user()
    if me.id not in [m.user1_id, m.user2_id]:
        return redirect(url_for('matches'))
    return render_template('messages.html', match_id=match_id)

@app.route('/profil')
@login_required
def profil():
    return render_template('profil.html')

@app.route('/recharger')
@login_required
def recharger():
    return render_template('recharger.html')

@app.route('/deconnexion')
def logout():
    session.clear()
    return redirect(url_for('index'))


# ══════════════════════════════════════════════
#  API AUTH
# ══════════════════════════════════════════════

@app.route('/api/inscription', methods=['POST'])
def api_inscription():
    d = request.get_json()

    # Vérification CGU acceptées
    if not d.get('cgu_accepte'):
        return jsonify({'success':False,'message':'Vous devez accepter les CGU pour continuer'})

    # Vérification âge minimum
    age = int(d.get('age', 0))
    if age < 18:
        return jsonify({'success':False,'message':'Vous devez avoir au moins 18 ans'})

    if User.query.filter_by(email=d['email']).first():
        return jsonify({'success':False,'message':'Email déjà utilisé'})
    if User.query.filter_by(username=d['username']).first():
        return jsonify({'success':False,'message':'Pseudo déjà pris'})

    pays   = (d.get('pays') or 'FR').upper()
    devise = (d.get('devise') or 'USD').upper()

    u = User(
        username=d['username'], email=d['email'],
        password=generate_password_hash(d['password']),
        prenom=d.get('prenom',''), age=age,
        sexe=d.get('sexe',''), ville=d.get('ville',''),
        bio=d.get('bio',''),
        interets=json.dumps(d.get('interets',[])),
        recherche=d.get('recherche','les_deux'),
        pays=pays, devise=devise,
        lat=d.get('lat'), lng=d.get('lng'),
        pieces=PIECES_INSCRIPTION,
        cgu_accepte=True,
    )
    db.session.add(u)
    db.session.commit()
    session['user_id'] = u.id
    return jsonify({
        'success':True,'redirect':'/decouvrir',
        'pieces_bienvenue':PIECES_INSCRIPTION
    })

@app.route('/api/connexion', methods=['POST'])
def api_connexion():
    d = request.get_json()
    u = User.query.filter_by(email=d['email']).first()
    if u and check_password_hash(u.password, d['password']):
        session['user_id'] = u.id
        u.derniere_connexion = datetime.utcnow()
        db.session.commit()
        return jsonify({'success':True,'redirect':'/decouvrir'})
    return jsonify({'success':False,'message':'Identifiants incorrects'})


# ══════════════════════════════════════════════
#  API GÉOLOCALISATION
# ══════════════════════════════════════════════

@app.route('/api/position', methods=['POST'])
@login_required
def api_position():
    me = current_user()
    d  = request.get_json()
    if d.get('lat') and d.get('lng'):
        me.lat = float(d['lat'])
        me.lng = float(d['lng'])
        if d.get('ville'):  me.ville = d['ville']
        if d.get('pays'):   me.pays  = d['pays'].upper()
        if d.get('devise'): me.devise = d['devise'].upper()
        db.session.commit()
        return jsonify({'success':True})
    return jsonify({'success':False})


# ══════════════════════════════════════════════
#  API PROFILS / SWIPE
# ══════════════════════════════════════════════

@app.route('/api/profils')
@login_required
def api_profils():
    me    = current_user()
    rayon = float(request.args.get('rayon', 9999))
    vus   = db.session.query(Like.to_user).filter_by(from_user=me.id).subquery()
    q = User.query.filter(User.id!=me.id, User.actif==True, ~User.id.in_(vus))
    if me.recherche and me.recherche != 'les_deux':
        q = q.filter(User.sexe == me.recherche)
    if me.age_min: q = q.filter(User.age >= me.age_min)
    if me.age_max: q = q.filter(User.age <= me.age_max)
    result = []
    for p in q.limit(60).all():
        d = haversine(me.lat, me.lng, p.lat, p.lng)
        if d is not None and d > rayon: continue
        result.append(p.to_dict(dist=d))
    result.sort(key=lambda x: x.get('distance_km') or 9999)
    return jsonify(result[:20])

@app.route('/api/like', methods=['POST'])
@login_required
def api_like():
    me = current_user()
    d  = request.get_json()
    tid, action = d.get('user_id'), d.get('action','like')
    if action == 'pass':
        return jsonify({'success':True,'match':False})
    if not Like.query.filter_by(from_user=me.id, to_user=tid).first():
        db.session.add(Like(from_user=me.id, to_user=tid))
        db.session.commit()
    if Like.query.filter_by(from_user=tid, to_user=me.id).first() and not find_match(me.id, tid):
        db.session.add(Match(user1_id=me.id, user2_id=tid))
        db.session.commit()
        return jsonify({'success':True,'match':True,'profil':User.query.get(tid).to_dict()})
    return jsonify({'success':True,'match':False})


# ══════════════════════════════════════════════
#  API MATCHES
# ══════════════════════════════════════════════

@app.route('/api/matches')
@login_required
def api_matches():
    me = current_user()
    ms = Match.query.filter(
        ((Match.user1_id==me.id)|(Match.user2_id==me.id)) & Match.actif
    ).all()
    out = []
    for m in ms:
        oid = m.user2_id if m.user1_id==me.id else m.user1_id
        o   = User.query.get(oid)
        if not o: continue
        lm  = Message.query.filter_by(match_id=m.id, bloque=False)\
                           .order_by(Message.date.desc()).first()
        r   = o.to_dict()
        r.update({
            'match_id':m.id,
            'dernier_message':lm.contenu[:50] if lm else None,
            'date_match':m.date.strftime('%d/%m/%Y')
        })
        out.append(r)
    return jsonify(out)


# ══════════════════════════════════════════════
#  API MESSAGES (avec modération)
# ══════════════════════════════════════════════

@app.route('/api/messages/<int:mid>')
@login_required
def api_get_messages(mid):
    me   = current_user()
    msgs = Message.query.filter_by(match_id=mid, bloque=False)\
                        .order_by(Message.date.asc()).all()
    Message.query.filter_by(match_id=mid, lu=False)\
        .filter(Message.expediteur!=me.id).update({'lu':True})
    db.session.commit()
    return jsonify([{
        'id':m.id,'contenu':m.contenu,
        'date':m.date.strftime('%H:%M'),
        'moi':m.expediteur==me.id
    } for m in msgs])

@app.route('/api/messages/envoyer', methods=['POST'])
@login_required
def api_send():
    me = current_user()
    d  = request.get_json()
    contenu = d.get('contenu','').strip()

    if not contenu:
        return jsonify({'success':False,'message':'Message vide'}), 400

    # ── MODÉRATION ──
    bloque, raison = analyser_message(contenu)
    if bloque:
        # Enregistrer le message bloqué
        me.messages_bloques = (me.messages_bloques or 0) + 1
        db.session.add(MessageBloque(
            user_id=me.id, contenu=contenu, raison=raison
        ))
        db.session.commit()

        messages_erreur = {
            'numéro_téléphone': '🚫 Partager des numéros de téléphone est interdit sur JUPITE. Continuez à discuter ici en toute sécurité !',
            'redirection_externe': '🚫 Les liens vers des applications externes (WhatsApp, Telegram, Instagram...) sont interdits. Restez sur JUPITE !',
            'contenu_inapproprié': '🚫 Ce message contient du contenu inapproprié et a été bloqué.',
        }
        return jsonify({
            'success':False,
            'code':'MESSAGE_BLOQUE',
            'message': messages_erreur.get(raison, '🚫 Message bloqué par la modération.')
        }), 403

    # ── VÉRIFICATION PIÈCES ──
    if me.pieces < COUT_PAR_MESSAGE:
        return jsonify({
            'success':False,'code':'PIECES_INSUFFISANTES',
            'message':f'Il vous faut {COUT_PAR_MESSAGE} pièces pour envoyer un message.',
            'pieces':me.pieces,'cout':COUT_PAR_MESSAGE
        }), 402

    me.pieces -= COUT_PAR_MESSAGE
    msg = Message(
        match_id=d['match_id'], expediteur=me.id,
        contenu=contenu, pieces_cout=COUT_PAR_MESSAGE
    )
    db.session.add(msg)
    db.session.commit()
    return jsonify({'success':True,'pieces':me.pieces,'cout':COUT_PAR_MESSAGE})


# ══════════════════════════════════════════════
#  API PIÈCES & PAIEMENT
# ══════════════════════════════════════════════

@app.route('/api/pieces/solde')
@login_required
def api_solde():
    me = current_user()
    return jsonify({
        'pieces':me.pieces,'cout_message':COUT_PAR_MESSAGE,
        'messages_possibles':me.pieces//COUT_PAR_MESSAGE,
        'est_cfa':me.est_cfa,'devise':me.devise,
        'symbole':SYMBOLES.get(me.devise, me.devise),
    })

@app.route('/api/pieces/offres')
@login_required
def api_offres():
    me     = current_user()
    devise = request.args.get('devise', me.devise).upper()
    est_cfa = me.est_cfa or devise in DEVISES_CFA
    return jsonify({
        'offres':[prix_offre(i, devise, est_cfa) for i in range(len(OFFRES))],
        'est_cfa':est_cfa,'devise':devise,
        'symbole':SYMBOLES.get(devise, devise),
        'cout_message':COUT_PAR_MESSAGE,
    })

@app.route('/api/pieces/acheter', methods=['POST'])
@login_required
def api_acheter():
    me  = current_user()
    d   = request.get_json()
    idx = int(d.get('offre_idx', 0))
    moyen  = d.get('moyen','carte')
    devise = (d.get('devise') or me.devise).upper()
    if idx < 0 or idx >= len(OFFRES):
        return jsonify({'success':False,'message':'Offre invalide'})
    est_cfa = me.est_cfa or devise in DEVISES_CFA
    p   = prix_offre(idx, devise, est_cfa)
    ref = 'JUP-'+uuid.uuid4().hex[:10].upper()
    tx  = Transaction(
        user_id=me.id, pieces=p['pieces'],
        montant_usd=p['usd_final'], montant_local=p['prix_local'],
        devise=devise, symbole=p['symbole'],
        moyen=moyen, reduction_cfa=est_cfa,
        reference=ref, statut='simule',
    )
    db.session.add(tx)
    me.pieces += p['pieces']
    me.pieces_total_achete += p['pieces']
    db.session.commit()
    return jsonify({
        'success':True,'reference':ref,
        'pieces_ajoutees':p['pieces'],
        'nouveau_solde':me.pieces,
        'montant':f"{p['prix_local']} {p['symbole']}",
        'reduction_cfa':est_cfa,
        'message':f"✅ {p['pieces']:,} pièces créditées !",
    })

@app.route('/api/pieces/historique')
@login_required
def api_historique():
    me  = current_user()
    txs = Transaction.query.filter_by(user_id=me.id)\
                           .order_by(Transaction.date.desc()).limit(30).all()
    return jsonify([{
        'id':t.id,'pieces':t.pieces,
        'montant':f"{t.montant_local} {t.symbole}",
        'moyen':t.moyen,'reference':t.reference,
        'reduction_cfa':t.reduction_cfa,
        'date':t.date.strftime('%d/%m/%Y %H:%M'),
        'statut':t.statut,
    } for t in txs])

@app.route('/api/devises')
def api_devises():
    return jsonify([
        {'code':k,'symbole':SYMBOLES.get(k,k),'taux_usd':v}
        for k,v in TAUX.items()
    ])


# ══════════════════════════════════════════════
#  API PROFIL
# ══════════════════════════════════════════════

@app.route('/api/profil/moi')
@login_required
def api_moi():
    me = current_user()
    d  = me.to_dict()
    d.update({
        'email':me.email,'recherche':me.recherche,
        'age_min':me.age_min,'age_max':me.age_max,
        'est_cfa':me.est_cfa,
    })
    return jsonify(d)

@app.route('/api/profil/modifier', methods=['POST'])
@login_required
def api_modifier():
    me = current_user()
    d  = request.get_json()
    for f in ['prenom','age','ville','bio','recherche','age_min','age_max','pays','devise']:
        if f in d: setattr(me, f, d[f])
    if 'interets' in d: me.interets = json.dumps(d['interets'])
    if d.get('lat'): me.lat = float(d['lat'])
    if d.get('lng'): me.lng = float(d['lng'])
    db.session.commit()
    return jsonify({'success':True})

@app.route('/api/stats')
@login_required
def api_stats():
    me = current_user()
    return jsonify({
        'likes_recus':  Like.query.filter_by(to_user=me.id).count(),
        'matches':      Match.query.filter((Match.user1_id==me.id)|(Match.user2_id==me.id)).count(),
        'messages':     Message.query.filter_by(expediteur=me.id, bloque=False).count(),
        'pieces':       me.pieces,
        'messages_possibles': me.pieces // COUT_PAR_MESSAGE,
        'messages_bloques': me.messages_bloques or 0,
    })


# ══════════════════════════════════════════════
#  PWA
# ══════════════════════════════════════════════

@app.route('/manifest.json')
def manifest():
    return jsonify({
        "name":"JUPITE","short_name":"JUPITE",
        "description":"L'application de rencontres JUPITE — 18+ confidentiel",
        "start_url":"/","display":"standalone",
        "background_color":"#0E0B14","theme_color":"#E8364A",
        "orientation":"portrait",
        "icons":[
            {"src":"/static/icons/icon-192.png","sizes":"192x192","type":"image/png"},
            {"src":"/static/icons/icon-512.png","sizes":"512x512","type":"image/png","purpose":"maskable"}
        ],
        "categories":["social","lifestyle"],
    }), 200, {'Content-Type':'application/manifest+json'}

@app.route('/sw.js')
def service_worker():
    sw = """
const CACHE='jupite-v3';
const ASSETS=['/','/decouvrir','/matches','/profil','/recharger','/cgu'];
self.addEventListener('install',e=>{
  e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS)).catch(()=>{}));
  self.skipWaiting();
});
self.addEventListener('activate',e=>{
  e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==CACHE).map(k=>caches.delete(k)))));
  self.clients.claim();
});
self.addEventListener('fetch',e=>{
  if(e.request.method!=='GET')return;
  e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)));
});
"""
    return sw, 200, {'Content-Type':'application/javascript'}


# ══════════════════════════════════════════════
#  INIT DB
# ══════════════════════════════════════════════

def seed():
    if User.query.count() > 0: return
    demos = [
        {'u':'sophie_m','e':'sophie@demo.com','p':'Sophie','a':26,'s':'femme','v':'Abidjan','pays':'CI','dev':'XOF','lat':5.35,'lng':-4.00},
        {'u':'thomas_r','e':'thomas@demo.com','p':'Thomas','a':29,'s':'homme','v':'Paris','pays':'FR','dev':'EUR','lat':48.85,'lng':2.35},
        {'u':'camille_d','e':'camille@demo.com','p':'Camille','a':24,'s':'femme','v':'Lomé','pays':'TG','dev':'XOF','lat':6.13,'lng':1.22},
        {'u':'lucas_b','e':'lucas@demo.com','p':'Lucas','a':31,'s':'homme','v':'Dakar','pays':'SN','dev':'XOF','lat':14.69,'lng':-17.44},
        {'u':'emma_v','e':'emma@demo.com','p':'Emma','a':27,'s':'femme','v':'Lyon','pays':'FR','dev':'EUR','lat':45.74,'lng':4.83},
        {'u':'kofi_a','e':'kofi@demo.com','p':'Kofi','a':30,'s':'homme','v':'Accra','pays':'GH','dev':'GHS','lat':5.56,'lng':-0.19},
        {'u':'ines_b','e':'ines@demo.com','p':'Inès','a':25,'s':'femme','v':'Casablanca','pays':'MA','dev':'MAD','lat':33.58,'lng':-7.59},
    ]
    for d in demos:
        u = User(
            username=d['u'],email=d['e'],
            password=generate_password_hash('demo1234'),
            prenom=d['p'],age=d['a'],sexe=d['s'],ville=d['v'],
            pays=d['pays'],devise=d['dev'],lat=d['lat'],lng=d['lng'],
            interets=json.dumps(['Voyage','Musique','Sport']),
            recherche='les_deux',pieces=PIECES_INSCRIPTION,
            cgu_accepte=True,
        )
        db.session.add(u)
    db.session.commit()
    print("✅ Données de démo créées")


# ══════════════════════════════════════════════
#  LANCEMENT
# ══════════════════════════════════════════════

import os

if __name__ == '__main__':
    os.makedirs('static/uploads', exist_ok=True)
    os.makedirs('static/icons', exist_ok=True)
    with app.app_context():
        db.create_all()
        seed()

    import platform
    port = int(os.environ.get('PORT', 5000))

    if platform.system() == 'Windows':
        from waitress import serve
        print(f"🚀 JUPITE → http://localhost:{port}")
        serve(app, host='0.0.0.0', port=port)
    else:
        print(f"🚀 JUPITE → port {port}")
        app.run(host='0.0.0.0', port=port)