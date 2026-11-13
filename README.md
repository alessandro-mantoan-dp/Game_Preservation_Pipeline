# Video Game Digital Preservation Pipeline

Un sistema modulare in Python per l'estrazione forense dei metadati tecnici, la standardizzazione archivistica e l'indicizzazione ricercabile di collezioni videoludiche DRM-free (es. GOG).

**Live Demo Interattiva:** [Esplora Archivio Online](https://game-preservation-pipeline.streamlit.app/)

## Architettura del Progetto

### Architettura Modulare (Standard OAIS / ISO 14721)

1. **Estrazione Forense e Baseline (`scripts/01_estrattore_gog.py`)**:
   - Analizza manifest GOG, intestazioni binarie PE Header (`x86`/`x64`) e librerie per dedurre il motore grafico.
   - Rileva gli **installer offline originali GOG** (`setup_*.exe` e file `.bin`) come pacchetti sorgente **SIP** e ne calcola le impronte crittografiche **SHA-256**.
   - Esclude i dati utente (salvataggi) tramite `config/esclusioni_audit.json` e genera il manifest crittografico immutabile dell'intero pacchetto installato.
2. **Standardizzazione XML e Validazione XSD (`scripts/02_generatore_xml.py`)**:
   - Genera record interoperabili conformi a **Dublin Core**, **MODS v3.8** e **PREMIS v3.0** (inclusi *Significant Properties*, valutazione curatoriale del rischio di obsolescenza, gestione diritti `premis:rights` e collegamento ai file sorgente SIP).
   - Certifica la conformità strutturale tramite validazione offline contro **schemi XSD** (`config/archivio_schema.xsd`).
3. **Indicizzazione Relazionale (`scripts/03_popola_database.py`)**:
   - Esegue il parsing XPath degli XML e popola il database **SQLite** mantenendo intatto lo storico dei Condition Report.
4. **Interrogazione CLI (`scripts/04_interroga_archivio.py`)**:
   - Interfaccia a riga di comando per query SQL/JOIN e report statistici rapidi.
5. **Dashboard Web Ibrida (`scripts/05_interfaccia_web.py`)**:
   - Interfaccia interattiva in **Streamlit** con filtri multi-criterio, ispezione XML, registro storico **Condition Report** ed esecuzione guidata dei moduli locali.
6. **Audit di Integrità e Condition Reporting (`scripts/06_audit_integrita.py` & `scripts/esporta_reports.py`)**:
   - Esegue controlli periodici (*Audit Rapido* sull'eseguibile o *Audit Profondo* sull'intero manifest) per rilevare fenomeni di *bit-rot* o alterazioni, registrando gli esiti nel database ed esportando schede leggibili in Markdown (`output_reports/`).
7. **Impacchettamento AIP BagIt (`scripts/07_esporta_bagit.py`)**:
   - Genera pacchetti di conservazione autocontenuti conformi allo standard **BagIt (RFC 8493)** (`bagit.txt`, `bag-info.txt`, `manifest-sha256.txt`, `tagmanifest-sha256.txt`) unendo i binari originali ai metadati XML e ai Condition Report.

## Struttura delle Cartelle

```text
Game_Preservation_Pipeline/
├── config/
│   ├── archivio_schema.xsd        # Schema master XSD per validazione offline
│   ├── esclusioni_audit.json      # Regole di esclusione per salvataggi e dati utente
│   ├── firme_engine.json          # Regole euristiche per il riconoscimento dei game engine
│   ├── metadati_manuali.json      # Override storico, rischio e Significant Properties per ID GOG
│   ├── premis_stub.xsd            # Stub locale per risoluzione offline tipi PREMIS
│   └── settings.example.json      # Template per i percorsi locali (giochi e installer)
├── demo_data/                     # Database e XML dimostrativi per la Live Demo pubblica
├── scripts/
│   ├── 01_estrattore_gog.py
│   ├── 02_generatore_xml.py
│   ├── 03_popola_database.py
│   ├── 04_interroga_archivio.py
│   ├── 05_interfaccia_web.py
│   ├── 06_audit_integrita.py
│   ├── 07_esporta_bagit.py
│   └── esporta_reports.py
├── output_json/                   # Output intermedi e manifest SHA-256 (ignorati da Git)
├── output_xml/                    # Pacchetti metadati DC + MODS + PREMIS (ignorati da Git)
├── output_reports/                # Condition Report storici in Markdown (ignorati da Git)
├── output_aip/                    # Pacchetti di conservazione BagIt RFC 8493 (ignorati da Git)
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

2. **Configura i percorsi della tua libreria:**
   Copia `config/settings.example.json` rinominandolo in `config/settings.json` e inserisci il percorso dei giochi installati e l'eventuale cartella di backup degli installer offline GOG (SIP):
   ```json
   {
       "gog_library_path": "C:\\Program Files\\GOG Galaxy\\Games",
       "gog_installers_path": "D:\\Game_Installer"
   }
   ```

3. **Avvia l'interfaccia web e sincronizza l'archivio:**
   ```bash
   streamlit run scripts/05_interfaccia_web.py
   ```
   Clicca sul pulsante **"Sincronizza Libreria GOG"** nella barra laterale per popolare automaticamente JSON, XML e Database.
