# DataGouv — explorer data.gouv.fr depuis l'agent

`datagouv.py` permet de **trouver des bases de données ouvertes** sur [data.gouv.fr](https://www.data.gouv.fr/datasets/search) à partir de mots-clés, de les **décrire**, puis de **générer un programme Python autonome** pour les exploiter (lecture, filtres, comptages, graphiques, export).

Aucune clé d'API n'est nécessaire. Le script n'utilise que la bibliothèque standard ; le programme généré utilise `pandas` et `matplotlib` (et `openpyxl` pour un fichier Excel).

## Utilisation

Depuis l'agent (sans IA, résultat immédiat) :

| Commande                            | Effet                                                                                                                                                        |
|---                                  |---                                                                                                                                                           |
| `/data chercher <mots>`             | Liste numérotée des jeux de données (producteur, formats, date de mise à jour, début de description)                                                         |
| `/data chercher suite`              | Page suivante (8 résultats par page) ; la numérotation continue (9, 10…), les numéros précédents restent valables, les doublons sont ignorés                 |
| `/data apis <mots>`                 | Liste des API publiques correspondantes                                                                                                                      |
| `/data infos <n°> [n° fichier]`     | Détail d'un résultat : producteur, licence, fichiers numérotés ; avec un n° de fichier : son **adresse directe** (URL complète)                              |
| `/data squelette <n°> [n° fichier]` | Génère le programme d'exploitation (par défaut : premier fichier CSV/Excel). `<n°>` = n° du **résultat**, `[n° fichier]` = n° du fichier affiché par `infos` |
| `/data siren <9 chiffres>`          | Fiche d'une entreprise : active ou cessée (Sirene, INSEE) + annonces de procédure collective (BODACC)                                                        |
| `/data check`                       | Diagnostic : vérifie l'accès à data.gouv.fr et la structure des réponses                                                                                     |

En conversation, l'IA peut aussi appeler l'outil `datagouv` (« cherche des bases sur… »). Son résultat est affiché tel quel.

Directement en ligne de commande : `python3 datagouv.py chercher <mots>` (mêmes sous-commandes ; `<n°>` peut être remplacé par l'identifiant ou le « slug » du jeu de données).

Le numéro `<n°>` est celui de la **dernière** recherche `chercher` (mémorisé dans `datagouv_last.json`) ; relancer `chercher` avec d'autres mots repart de 1. L'ordre des résultats d'une même recherche peut légèrement varier d'un appel à l'autre : se fier à la dernière liste affichée.

## Bien chercher

La recherche de data.gouv.fr exige **tous** les mots saisis : mieux vaut 1 ou 2 mots précis qu'une phrase. Si rien n'est trouvé, la commande essaie le singulier, puis retire des mots et le signale. Conseils :
- partir du **thème** (« pépinières », « sirene », « logement »), puis affiner avec un lieu ou un producteur ;
- tester un synonyme ou le singulier ;
- regarder les formats annoncés (`csv`, `xlsx`) : seuls ceux-là donnent un programme ;
- lire la ligne de description sous chaque titre pour juger la pertinence avant `infos` ;
- `chercher suite` pour parcourir les pages suivantes d'une recherche large.

En conversation, l'IA peut enchaîner plusieurs recherches avec des mots différents et comparer.

## Fiche entreprise (`siren`)

Nécessite une clé d'API Sirene gratuite (portail-api.insee.fr : créer une application, puis souscrire à l'API Sirene). La clé se place dans un fichier `.env` à côté de `datagouv.py` :

```
INSEE_API_KEY_SIREN=votre_clé
```

Une ligne `NOM=valeur`, sans espace autour du `=` ni guillemets ; `chmod 600 .env`. La clé n'est jamais affichée. Le fichier `.env` ne doit pas être publié (à ajouter au `.gitignore`).

Le numéro est validé (9 chiffres, clé de contrôle). Les entrepreneurs individuels (personnes physiques) ne sont pas détaillés. Le BODACC est interrogé sans clé ; s'il est injoignable, la fiche le signale au lieu d'affirmer l'absence de procédure.

## Le programme généré

Écrit dans `programmes/exploiter_<jeu>.py`. Il est **indépendant** de l'agent et n'est **jamais lancé** par lui.

```
python3 exploiter_<jeu>.py --colonnes                     # colonnes, types, valeurs manquantes
python3 exploiter_<jeu>.py --apercu 20                    # premières lignes
python3 exploiter_<jeu>.py --filtre "COL=valeur"          # lignes dont COL contient valeur
python3 exploiter_<jeu>.py --top COL 15                   # valeurs les plus fréquentes
python3 exploiter_<jeu>.py --graphe COL --sortie g.png
python3 exploiter_<jeu>.py --export extrait.csv
python3 exploiter_<jeu>.py --maj                          # retélécharger le fichier
python3 exploiter_<jeu>.py --lignes 100000 --colonnes     # gros fichier : ne lit que les 100 000 premières lignes
python3 exploiter_<jeu>.py --membre nom.csv               # archive ZIP : choisir le fichier à lire
python3 exploiter_<jeu>.py --url ADRESSE --maj            # utiliser l'adresse directe d'un autre fichier CSV/Excel
```

Chaque commande tient sur **une seule ligne** : en copiant l'« Essai » affiché par l'agent, vérifier que la ligne n'a pas été coupée (une option isolée sur la ligne suivante est lue comme une commande du terminal : « commande introuvable »).

Le fichier est téléchargé une fois dans `programmes/donnees/`. La lecture gère les CSV français (séparateur `;` ou `,`, encodage UTF-8, Windows-1252 ou Latin-1 — l'encodage lu est affiché —, virgule décimale) et réduit les suites d'espaces des colonnes texte. Un caractère déjà perdu dans le fichier d'origine (par exemple une apostrophe devenue `?`) ne peut pas être récupéré. Un garde-fou interrompt le téléchargement (et l'extraction d'une archive) au-delà de 1 Go (constante `TAILLE_MAX_MO` du programme). Pandas charge le fichier en mémoire : un CSV de 1 Go peut demander plusieurs Go de RAM ; pour un gros fichier, commencer par `--lignes 100000`.

**Archives ZIP** : `squelette` accepte un fichier au format zip. Le programme décompresse seul le premier fichier CSV/TSV/Excel de l'archive (`--membre` pour en choisir un autre), vérifie la taille réellement décompressée et ignore les chemins internes de l'archive. Si elle ne contient que des données géographiques (shapefile…), il liste son contenu et s'arrête.

**Adresses (URL)** : `infos <n°> <n° fichier>` affiche l'adresse directe d'un fichier. Cette adresse se passe au programme avec `--url ADRESSE --maj`. Une adresse qui ouvre une page web (et non un téléchargement) est refusée. Si l'adresse du producteur renvoie une page web au lieu d'un fichier (cas de certains « exports » à construire sur un site), `squelette` refuse de générer le programme, et le programme généré s'arrête avec un message clair ; `--url` permet alors de fournir l'adresse directe d'un export. Le programme est un point de départ : il se modifie librement.

## Sécurité

- Lecture seule sur le réseau ; seuls data.gouv.fr (recherches), l'INSEE et le BODACC (`siren`) sont interrogés ; les coupures passagères sont retentées 2 fois.
- Adresses `https` publiques uniquement (adresses privées ou locales refusées, redirections contrôlées).
- Références (numéro, identifiant) et mots-clés strictement validés ; aucune donnée issue du réseau n'est insérée telle quelle dans le code généré.
- Le script ne lance qu'une chose : l'écriture d'un fichier `.py` dans `programmes/`.

## Limites

- `squelette` prend en charge les fichiers CSV, TSV, Excel et les archives ZIP qui en contiennent (les formats géographiques — geojson, shapefile… — ne sont pas gérés).
- Un jeu de données sur des **personnes** peut relever du RGPD : vérifier la licence et l'usage autorisé avant toute réutilisation.
- Les données sont celles des producteurs : leur qualité et leur fraîcheur varient (date de mise à jour affichée).
- `siren` ne couvre que les personnes morales ; une absence d'annonce BODACC ne vaut pas attestation : vérifier sur bodacc.fr.

## Fichiers

| Fichier                | Rôle                                                                  |
|---                     |---                                                                    |
| `datagouv.py`          | Le script                                                             |
| `programmes/`          | Programmes générés (et `programmes/donnees/` : fichiers téléchargés)  |
| `datagouv_last.json`   | Derniers résultats de `chercher`                                      |
| `.env`                 | Clé d'API Sirene (privé, jamais publiée)                              |

À ajouter au `.gitignore` : `programmes/`, `datagouv_last.json`, `.env`.
