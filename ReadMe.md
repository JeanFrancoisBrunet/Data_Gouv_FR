# DataGouv — explorer data.gouv.fr depuis l'agent

`datagouv.py` permet de **trouver des bases de données ouvertes** sur [data.gouv.fr](https://www.data.gouv.fr/datasets/search) à partir de mots-clés, de les **décrire**, puis de **générer un programme Python autonome** pour les exploiter (lecture, filtres, comptages, graphiques, export).

Aucune clé d'API n'est nécessaire. Le script n'utilise que la bibliothèque standard ; le programme généré utilise `pandas` et `matplotlib` (et `openpyxl` pour un fichier Excel).

## Utilisation

Depuis l'agent (sans IA, résultat immédiat) :

| Commande                            | Effet                                                                                                 |
|---                                  |---                                                                                                    |
| `/data chercher <mots>`             | Liste numérotée des jeux de données (producteur, formats, date de mise à jour, début de description)  |
| `/data chercher suite`              | Page suivante de la dernière recherche                                                                |
| `/data apis <mots>`                 | Liste des API publiques correspondantes                                                               |
| `/data infos <n°>`                  | Détail d'un résultat : producteur, licence, fichiers numérotés                                        |
| `/data squelette <n°> [n° fichier]` | Génère le programme d'exploitation (par défaut : premier fichier CSV/Excel)                           |
| `/data siren <9 chiffres>`          | Fiche d'une entreprise : active ou cessée (Sirene, INSEE) + annonces de procédure collective (BODACC) |
| `/data check`                       | Diagnostic : vérifie l'accès à data.gouv.fr et la structure des réponses                              |

En conversation, l'IA peut aussi appeler l'outil `datagouv` (« cherche des bases sur… »). Son résultat est affiché tel quel.

Directement en ligne de commande : `python3 datagouv.py chercher <mots>` (mêmes sous-commandes ; `<n°>` peut être remplacé par l'identifiant ou le « slug » du jeu de données).

Le numéro `<n°>` est celui de la **dernière** recherche `chercher` (mémorisé dans `datagouv_last.json`).

## Bien chercher

La recherche de data.gouv.fr exige **tous** les mots saisis : mieux vaut 1 ou 2 mots précis qu'une phrase. Si rien n'est trouvé, la commande essaie le singulier, puis retire des mots et le signale. Conseils :
- partir du **thème** (« pépinières », « sirene », « logement »), puis affiner avec un lieu ou un producteur ;
- tester un synonyme ou le singulier ;
- regarder les formats annoncés (`csv`, `xlsx`) : seuls ceux-là donnent un programme ;
- lire la ligne de description sous chaque titre pour juger la pertinence avant `infos`.

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
```

Le fichier est téléchargé une fois dans `programmes/donnees/`. La lecture gère les CSV français (séparateur `;` ou `,`, encodage UTF-8, Windows-1252 ou Latin-1 — l'encodage lu est affiché —, virgule décimale) et réduit les suites d'espaces des colonnes texte. Un caractère déjà perdu dans le fichier d'origine (par exemple une apostrophe devenue `?`) ne peut pas être récupéré. Le programme est un point de départ : il se modifie librement.

## Sécurité

- Lecture seule sur le réseau ; seuls les hôtes de data.gouv.fr sont interrogés pour les recherches.
- Adresses `https` publiques uniquement (adresses privées ou locales refusées, redirections contrôlées).
- Références (numéro, identifiant) et mots-clés strictement validés ; aucune donnée issue du réseau n'est insérée telle quelle dans le code généré.
- Le script ne lance qu'une chose : l'écriture d'un fichier `.py` dans `programmes/`.

## Limites

- Seuls les fichiers CSV, TSV et Excel sont pris en charge par `squelette`.
- Un jeu de données sur des **personnes** peut relever du RGPD : vérifier la licence et l'usage autorisé avant toute réutilisation.
- Les données sont celles des producteurs : leur qualité et leur fraîcheur varient (date de mise à jour affichée).
- `siren` ne couvre que les personnes morales ; une absence d'annonce BODACC ne vaut pas attestation : vérifier sur bodacc.fr.

## Fichiers

| Fichier                | Rôle                                                                  |
|---                     |---                                                                    |
| `datagouv.py`          | Le script                                                             |
| `programmes/`          | Programmes générés (et `programmes/donnees/` : fichiers téléchargés)  |
| `datagouv_last.json`   | Derniers résultats de `chercher`                                      |

| `.env` | Clé d'API Sirene (privé) |

À ajouter au `.gitignore` : `programmes/`, `datagouv_last.json`, `.env`.
