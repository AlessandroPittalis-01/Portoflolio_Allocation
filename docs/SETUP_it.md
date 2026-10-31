# Guida di installazione (per chi usa GitHub per la prima volta)

Questa guida porta il progetto da zero a funzionante. Se un passaggio non è chiaro, fermati lì e chiedi.
I nomi dei menu di GitHub possono cambiare leggermente nel tempo.

## 1. Idee di base (2 minuti)

- **GitHub** è un archivio online per il codice. Un **repository** è la cartella del progetto su GitHub.
- **Codespace** è un computer temporaneo nel browser (con VS Code) collegato al repository. Il codice gira lì.
- **Commit** = salvare una versione nella cronologia. **Push** = inviarla a GitHub.
- ATTENZIONE: i file che esistono solo dentro il Codespace e NON sono stati inviati con push possono andare persi
  se il Codespace viene eliminato (per inattività prolungata o per errore). Il repository su GitHub è il tuo backup.
  Regola: a fine sessione, sempre `commit` e `push`.

## 2. Creare il repository (una volta sola)

1. Vai su github.com e accedi.
2. In alto a destra clicca **+** → **New repository**.
3. Nome: `portfolio-risk-manager`. Scegli **Private** (privato).
4. Spunta **Add a README file** (così il repository ha già un ramo `main`).
5. Clicca **Create repository**.

(Se hai già un repository che vuoi usare, saltalo e usa quello.)

## 3. Aprire il Codespace

1. Nella pagina del repository clicca il pulsante verde **Code**.
2. Scheda **Codespaces** → **Create codespace on main**.
3. Attendi: si apre VS Code nel browser. A sinistra c'è l'elenco dei file, in basso il terminale.
   Se il terminale non si vede: menu **Terminal** → **New Terminal**.

GitHub offre una quota mensile gratuita di ore di Codespaces: controlla il tuo consumo nelle impostazioni dell'account.

## 4. Caricare i file del progetto

1. Trascina `portfolio-risk-manager.zip` nell'elenco dei file a sinistra (area **Explorer**).
2. Nel terminale scrivi, una riga alla volta:

```bash
unzip -o portfolio-risk-manager.zip -d /tmp/prm
cp -r /tmp/prm/portfolio-risk-manager/. .
rm portfolio-risk-manager.zip
```

Ora i file del progetto sono nella cartella principale (vedrai `README.md`, `pipeline/`, `src/`, `config/`...).

## 5. Installare e provare (una volta per Codespace)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

- `venv` crea un ambiente Python pulito dentro il progetto.
- `source .venv/bin/activate` lo attiva: vedrai `(.venv)` all'inizio della riga. **Va rifatto ogni volta che apri un nuovo terminale.**
- `pip install -e ".[dev]"` installa le librerie (pandas, yfinance, pytest...).
- `pytest` esegue i test. Risultato atteso: una riga finale verde, circa `44 passed`.

Se `pytest` mostra errori, copia l'intero messaggio e mandalo.

## 6. Primo uso: scaricare i dati (stadio 01)

Per trovare i simboli Yahoo giusti partendo dall'ISIN (il codice unico del fondo):

```bash
python pipeline/01_sourcing.py --find
```

Per ogni ETF senza simbolo confermato stampa le quotazioni che Yahoo conosce (simbolo, borsa, nome del fondo).
Controlla che il nome sia il fondo giusto e scegli la quotazione su una borsa in euro (XETRA, Amsterdam, Milano).
Incolla il risultato nella chat: ti dirò le righe da cambiare. Per provare invece simboli ipotizzati:

```bash
python pipeline/01_sourcing.py --probe
```

Prova i simboli ipotizzati degli ETF e stampa quali funzionano (non scrive file). Incolla il risultato nella chat:
ti dirò quali righe cambiare in `config/universe_candidates.yaml` (si sostituisce `verify` con il simbolo giusto).

Dopo aver confermato i simboli:

```bash
python pipeline/01_sourcing.py
```

Scarica i prezzi e crea due tabelle in `data/processed/`:
`prices_adj_close.csv` (prezzi) e `quality_report.csv` (controlli di qualità). Altre opzioni:

```bash
python pipeline/01_sourcing.py --refresh              # ignora la copia locale e riscarica
python pipeline/01_sourcing.py --assets dev_equity    # solo alcuni ETF
```

## 7. Salvare su GitHub (a fine sessione)

```bash
git add -A
git commit -m "Descrivi in breve cosa hai fatto"
git push
```

La prima volta git può chiedere nome ed email. In quel caso:

```bash
git config --global user.name "Il tuo nome"
git config --global user.email "la tua email"
```

(Nei Codespaces di solito è già configurato con il tuo account.)

## 8. Riprendere il lavoro un altro giorno

- Vai su github.com/codespaces e riapri il tuo Codespace (oppure repository → **Code** → **Codespaces**).
- Nel terminale: `source .venv/bin/activate`.
- Se il Codespace è stato eliminato: creane uno nuovo dal repository (passo 3) e rifai il passo 5. I file inviati con `push` ci sono ancora.

## Problemi frequenti

| Problema | Cosa fare |
|---|---|
| `unzip: command not found` | In alternativa clic destro sullo zip nell'Explorer → "Extract" se disponibile, oppure chiedi aiuto |
| `ModuleNotFoundError: prm` | Ambiente non attivo o installazione mancante: `source .venv/bin/activate` e `pip install -e ".[dev]"` |
| Yahoo risponde "Too many requests" | Aspetta qualche minuto e rilancia: i dati già scaricati restano in cache |
| `git push` rifiutato | Copia il messaggio completo e mandalo |
| `not a git repository` | Sei fuori dalla cartella del repository, oppure hai creato la cartella senza repository: usa il passo 2-3 |
