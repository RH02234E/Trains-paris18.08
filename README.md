# Vigietaxi — Arrivées gares parisiennes (PWA)

Application web progressive (PWA) : suivi des arrivées grandes lignes (TGV INOUI, OUIGO,
Intercités, Intercités de nuit, TGV Lyria, ICE, Eurostar Bruxelles, Eurostar Londres) dans les
6 gares parisiennes, regroupées par créneaux de 30 minutes ou 1 heure, avec un résumé des
meilleurs moments pour se positionner à chaque gare.

Données du **18/08/2026** (301 arrivées, hors TER / RER / Transilien).

## Déploiement sur GitHub Pages

1. Crée un repo GitHub (public, sinon Pages nécessite un compte payant), par exemple `vigietaxi-app`.
2. Place tout le contenu de ce dossier (`index.html`, `style.css`, `app.js`, `manifest.json`,
   `service-worker.js`, le dossier `icons/`, le dossier `data/`, ce `README.md`) à la racine du repo.
3. Commit + push sur la branche `main`.
4. Dans GitHub : **Settings → Pages → Build and deployment → Source : Deploy from a branch**,
   choisis la branche `main` et le dossier `/ (root)`, puis **Save**.
5. Après 1-2 minutes, l'app est disponible sur :
   `https://<ton-pseudo-github>.github.io/<nom-du-repo>/`
6. Sur iPhone/Android, ouvre ce lien dans le navigateur puis **Partager → Sur l'écran d'accueil**
   (iOS) ou utilise le bouton **Installer** qui apparaît dans l'app (Android/Chrome) pour
   l'ajouter comme une vraie application.

Aucun serveur ni backend requis : tout est statique (HTML/CSS/JS + un fichier JSON de données).

## Mettre à jour les horaires (jour suivant)

Les données affichées sont un **instantané figé** du 18/08/2026 — ce n'est pas un flux temps
réel. Pour actualiser :

- Remplace le contenu de `data/data.json` par une nouvelle extraction (même structure : voir
  `stations`, `trains`, `slots30`, `slots60`, `summary`, `global`).
- Pour la partie SNCF (grandes lignes), la donnée source est le GTFS officiel SNCF Open Data
  (`https://ressources.data.sncf.com`, dataset horaires théoriques et temps réel), filtré sur
  les 6 gares et la date voulue.
- Pour Eurostar Londres → Gare du Nord, la donnée n'est pas dans le flux SNCF : il faut la
  récupérer séparément sur eurostar.com (page horaires Londres → Paris Gare du Nord).
- Recommit `data/data.json` et repush : GitHub Pages se met à jour automatiquement.

Si tu veux une mise à jour automatique quotidienne (sans repasser par une extraction manuelle),
ça nécessite un petit script planifié (GitHub Actions par exemple) qui régénère `data.json`
chaque jour et le commit — dis-le moi si tu veux que je le prépare.

## Structure du projet

```
index.html          page unique de l'app (vue d'ensemble + détail par gare)
style.css            styles (charte Vigietaxi : noir / or)
app.js                logique d'affichage, créneaux 30min/1h, résumé
manifest.json         manifeste PWA (icônes, nom, couleurs)
service-worker.js     mise en cache offline (app + dernières données connues)
icons/                icônes de l'app (192, 512, apple-touch, favicon)
data/data.json        données du jour (arrivées + agrégats par créneau + résumés)
```

## Limites connues

- Horaires **prévus** (théoriques), pas temps réel : retards/suppressions non reflétés.
- Eurostar Londres extrait automatiquement du site eurostar.com (pas d'API officielle) —
  à revérifier en cas de doute sur un horaire précis.
- Périmètre volontairement limité aux grandes lignes (pas de RER / Transilien / TER).
