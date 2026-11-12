# Video Game Digital Preservation Pipeline

Un sistema modulare in Python per l'estrazione forense dei metadati tecnici, la standardizzazione archivistica e l'indicizzazione ricercabile di collezioni videoludiche DRM-free (es. GOG).

## Architettura del Progetto

La pipeline è suddivisa in **5 moduli indipendenti** progettati secondo i principi della *Digital Curation* e del modello OAIS:

1. **Estrazione Forense (`scripts/01_estrattore_gog.py`)**:
   * Scansiona le cartelle dei giochi installati e legge i manifest ufficiali di GOG (`goggame-*.info`).
   * Ispeziona i **PE Header** degli eseguibili Windows per estrarre l'architettura CPU (`x86` / `x64`), il timestamp originale di compilazione UTC e le informazioni di versione.
   * Calcola l'impronta crittografica **SHA-256** (*fixity*) del binario principale.
   * Deduce il motore grafico tramite un dizionario euristico esterno basato su librerie ed estensioni proprietarie (`config/firme_engine.json`).

2. **Standardizzazione Archivistica (`scripts/02_generatore_xml.py`)**:
   * Traduce i dati grezzi JSON in documenti XML interoperabili conformi agli standard internazionali **Dublin Core (DC)**, **MODS v3.8** e **PREMIS v3.0**.
   * Integra un registro di override curato (`config/metadati_manuali.json`) per arricchire i metadati storici mancanti nei file binari più datati.

3. **Modellazione Relazionale (`scripts/03_popola_database.py`)**:
   * Esegue il parsing **XPath** dei file XML e normalizza i dati in un database **SQLite** strutturato su tre tabelle relazionali (`giochi`, `oggetti_digitali`, `ambienti_eventi`).

4. **Interrogazione Forense CLI (`scripts/04_interroga_archivio.py`)**:
   * Interfaccia a riga di comando per eseguire query SQL relazionali (`JOIN`), filtrare per engine/architettura e verificare impronte **SHA-256**.

5. **Interfaccia Web Interattiva (`scripts/05_interfaccia_web.py`)**:
   * Applicazione web sviluppata con **Streamlit** per esplorare il catalogo con filtri avanzati incrociati, ispezionare le schede divise per standard, scaricare i file XML e sincronizzare l'intera pipeline con un clic.

## Struttura delle Cartelle

```text
Game_Preservation_Pipeline/
├── config/
│   ├── firme_engine.json          # Regole euristiche per il riconoscimento dei game engine
│   ├── metadati_manuali.json      # Override storico curato per ID GOG
│   └── settings.example.json      # Template per il percorso della libreria locale
├── scripts/
│   ├── 01_estrattore_gog.py
│   ├── 02_generatore_xml.py
│   ├── 03_popola_database.py
│   ├── 04_interroga_archivio.py
│   └── 05_interfaccia_web.py
├── output_json/                   # Output intermedi normalizzati (ignorati da Git)
├── output_xml/                    # Pacchetti metadati DC + MODS + PREMIS (ignorati da Git)
├── database/                      # Database SQLite locale (ignorato da Git)
├── .gitignore
├── requirements.txt
└── README.md
```

## Installazione e Avvio

1. **Clona il repository e installa le dipendenze:**
   ```bash
   git clone https://github.com/alessandro-mantoan-dp/Game_Preservation_Pipeline.git
   cd Game_Preservation_Pipeline
   pip install -r requirements.txt
   ```

2. **Configura il percorso della tua libreria:**
   Copia `config/settings.example.json` rinominandolo in `config/settings.json` e inserisci il percorso della tua cartella dei giochi GOG:
   ```json
   {
       "gog_library_path": "C:\\Program Files\\GOG Galaxy\\Games"
   }
   ```

3. **Avvia l'interfaccia web e sincronizza l'archivio:**
   ```bash
   streamlit run scripts/05_interfaccia_web.py
   ```
   Clicca sul pulsante **"Sincronizza Libreria GOG"** nella barra laterale per popolare automaticamente JSON, XML e Database.
