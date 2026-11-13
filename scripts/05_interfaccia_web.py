import re
import sys
import sqlite3
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from esporta_reports import aggiorna_file_condition_report
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent.parent

st.set_page_config(
    page_title="Archivio Digitale Videogiochi",
    page_icon="🕹️",
    layout="wide"
)

st.markdown("""
    <style>
        .stProgress > div > div > div > div {
            background-color: #00FF41;
        }
    </style>
""", unsafe_allow_html=True)

PERCORSO_DB_LOCALE = BASE_DIR / "database" / "archivio_giochi.db"
CARTELLA_XML_LOCALE = BASE_DIR / "output_xml"
FILE_SETTINGS = BASE_DIR / "config" / "settings.json"

PERCORSO_DB_DEMO = BASE_DIR / "demo_data" / "demo_archivio.db"
CARTELLA_XML_DEMO = BASE_DIR / "demo_data" / "xml"
CARTELLA_SCRIPTS = BASE_DIR / "scripts"

MODALITA_LOCALE = FILE_SETTINGS.exists() and PERCORSO_DB_LOCALE.exists()

if MODALITA_LOCALE:
    PERCORSO_DB = PERCORSO_DB_LOCALE
    CARTELLA_XML = CARTELLA_XML_LOCALE
else:
    PERCORSO_DB = PERCORSO_DB_DEMO
    CARTELLA_XML = CARTELLA_XML_DEMO

def estrai_mb(testo_estensione: str) -> float:
    if not testo_estensione:
        return 0.0
    match = re.search(r"\(([\d\.]+)\s*MB\)", testo_estensione)
    return float(match.group(1)) if match else 0.0

def estrai_anno(data_str: str) -> int:
    if data_str and len(data_str) >= 4 and data_str[:4].isdigit():
        return int(data_str[:4])
    return 2000

def carica_dati_archivio():
    if not PERCORSO_DB.exists():
        return []

    conn = sqlite3.connect(PERCORSO_DB)
    conn.row_factory = sqlite3.Row
    cursore = conn.cursor()

    query = """
        SELECT 
            g.id_gioco,
            g.titolo,
            g.sviluppatore,
            g.publisher,
            g.data_rilascio,
            g.versione_edizione,
            g.lingua,
            g.descrizione_fisica,
            g.note_formati,
            o.percorso_relativo AS eseguibile,
            o.dimensione_byte AS dim_exe_byte,
            o.algoritmo_hash,
            o.valore_hash,
            o.formato_binario,
            a.descrizione AS game_engine
        FROM giochi g
        LEFT JOIN oggetti_digitali o ON g.id_gioco = o.id_gioco
        LEFT JOIN ambienti_eventi a ON g.id_gioco = a.id_gioco 
            AND a.categoria = 'software_environment' 
            AND a.tipo = 'game engine'
        ORDER BY g.titolo ASC;
    """
    cursore.execute(query)
    righe = []
    for r in cursore.fetchall():
        d = dict(r)
        d["dimensione_mb_num"] = estrai_mb(d["descrizione_fisica"])
        d["anno_num"] = estrai_anno(d["data_rilascio"])
        righe.append(d)
    conn.close()
    return righe

def carica_eventi_gioco(id_gioco: str):
    conn = sqlite3.connect(PERCORSO_DB)
    conn.row_factory = sqlite3.Row
    cursore = conn.cursor()
    cursore.execute("""
        SELECT categoria, tipo, descrizione, data_registrazione
        FROM ambienti_eventi
        WHERE id_gioco = ?
        ORDER BY data_registrazione ASC;
    """, (id_gioco,))
    eventi = [dict(r) for r in cursore.fetchall()]
    conn.close()
    return eventi

def carica_condition_reports(id_gioco: str):
    conn = sqlite3.connect(PERCORSO_DB)
    conn.row_factory = sqlite3.Row
    cursore = conn.cursor()
    cursore.execute("""
        CREATE TABLE IF NOT EXISTS condition_reports (
            id_report INTEGER PRIMARY KEY AUTOINCREMENT,
            id_gioco TEXT NOT NULL,
            data_ispezione TEXT NOT NULL,
            tipo_operazione TEXT NOT NULL,
            agente TEXT NOT NULL,
            stato_integrita TEXT NOT NULL,
            manifest_riferimento TEXT,
            hash_rilevato TEXT,
            note_tecniche TEXT
        );
    """)
    cursore.execute("""
        SELECT id_report, data_ispezione, tipo_operazione, agente, stato_integrita, manifest_riferimento, hash_rilevato, note_tecniche
        FROM condition_reports
        WHERE id_gioco = ?
        ORDER BY data_ispezione DESC;
    """, (id_gioco,))
    reports = [dict(r) for r in cursore.fetchall()]
    conn.close()
    return reports

def aggiungi_condition_report_manuale(id_gioco: str, tipo_op: str, agente: str, stato: str, note: str):
    conn = sqlite3.connect(PERCORSO_DB)
    cursore = conn.cursor()
    data_ora = datetime.now(timezone.utc).isoformat()
    cursore.execute("""
        INSERT INTO condition_reports (
            id_gioco, data_ispezione, tipo_operazione, agente,
            stato_integrita, manifest_riferimento, hash_rilevato, note_tecniche
        ) VALUES (?, ?, ?, ?, ?, NULL, NULL, ?);
    """, (id_gioco, data_ora, tipo_op, agente, stato, note))
    conn.commit()
    conn.close()
    aggiorna_file_condition_report(PERCORSO_DB, id_gioco)

def esegui_script_con_stato(comando_lista: list, fase_iniziale: str):
    box_gioco = st.sidebar.empty()
    box_operazione = st.sidebar.empty()

    gioco_corrente = fase_iniziale
    box_gioco.markdown(f"**{gioco_corrente}**")
    box_operazione.caption("Inizializzazione processo...")

    comando_unbuffered = [comando_lista[0], "-u"] + comando_lista[1:]

    processo = subprocess.Popen(
        comando_unbuffered,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1
    )

    while True:
        riga = processo.stdout.readline()
        if not riga and processo.poll() is not None:
            break
        riga = riga.strip()
        if not riga or riga.startswith("---"):
            continue

        if riga.startswith("Avvio scansione di:"):
            gioco_corrente = riga.replace("Avvio scansione di:", "").replace("...", "").strip()
            box_gioco.markdown(f"**{gioco_corrente}**")
            box_operazione.caption("Scansione file e metadati GOG...")

        elif riga.startswith("PROGRESSO|"):
            parti = riga.split("|", 2)
            if len(parti) == 3:
                messaggio = parti[2]
                if ":" in messaggio:
                    titolo_part, dettaglio_part = messaggio.split(":", 1)
                    gioco_corrente = titolo_part.replace("Audit ", "").strip()
                    box_gioco.markdown(f"**{gioco_corrente}**")
                    box_operazione.caption(f"Calcolo integrita SHA-256: {dettaglio_part.strip()}")
                else:
                    box_operazione.caption(messaggio)

        elif riga.startswith("[") and "->" in riga:
            intestazione, esito = riga.split("->", 1)
            if "]" in intestazione:
                gioco_corrente = intestazione.split("]", 1)[1].strip()
                box_gioco.markdown(f"**{gioco_corrente}**")
            box_operazione.caption(esito.strip())

        else:
            box_operazione.caption(riga)

    box_gioco.empty()
    box_operazione.empty()

    if processo.returncode != 0:
        err = processo.stderr.read()
        st.sidebar.error(f"Errore durante l'esecuzione:\n{err}")
        st.stop()

st.title("Archivio di Preservazione Digitale — Videogiochi")
st.markdown("Catalogo basato sugli standard internazionali **Dublin Core**, **MODS** e **PREMIS**.")

st.sidebar.header("Ricerca e Filtri Avanzati")

if MODALITA_LOCALE:
    if st.sidebar.button("Sincronizza Libreria GOG", use_container_width=True):
        esegui_script_con_stato([sys.executable, str(CARTELLA_SCRIPTS / "01_estrattore_gog.py")], "Modulo 1: Estrazione Forense")
        esegui_script_con_stato([sys.executable, str(CARTELLA_SCRIPTS / "02_generatore_xml.py")], "Modulo 2: Generazione XML")
        esegui_script_con_stato([sys.executable, str(CARTELLA_SCRIPTS / "03_popola_database.py")], "Modulo 3: Aggiornamento Database")
        st.sidebar.success("Archivio aggiornato con successo.")
        st.rerun()

    col_btn1, col_btn2 = st.sidebar.columns(2)
    if col_btn1.button("Audit Rapido", help="Verifica solo l'eseguibile principale", use_container_width=True):
        esegui_script_con_stato([sys.executable, str(CARTELLA_SCRIPTS / "06_audit_integrita.py"), "--rapido"], "Audit Rapido Eseguibili")
        st.sidebar.success("Audit rapido completato.")
        st.rerun()

    if col_btn2.button("Audit Profondo", help="Verifica tutti i file contro il manifest SHA-256", use_container_width=True):
        esegui_script_con_stato([sys.executable, str(CARTELLA_SCRIPTS / "06_audit_integrita.py"), "--profondo"], "Audit Profondo Pacchetti")
        st.sidebar.success("Audit profondo completato.")
        st.rerun()
else:
    st.sidebar.info("**Modalità Demo Pubblica**\n\nStai esplorando un catalogo pre-indicizzato. Per scansionare la tua libreria locale, clona il repository su PC.")

st.sidebar.divider()

dati_completi = carica_dati_archivio()

if not dati_completi:
    st.warning("Il database è attualmente vuoto o non ancora creato. Clicca su **'Sincronizza Libreria GOG'** nella barra laterale (assicurati di aver configurato `config/settings.json`).")
    st.stop()

testo_ricerca = st.sidebar.text_input(
    "Parola chiave o Hash SHA-256",
    placeholder="Titolo, ID GOG o impronta file..."
).strip().lower()

lista_dev = sorted({g["sviluppatore"] for g in dati_completi if g["sviluppatore"]})
dev_scelto = st.sidebar.selectbox("Sviluppatore (dc:creator)", ["Tutti"] + lista_dev)

lista_engine = sorted({g["game_engine"] for g in dati_completi if g["game_engine"]})
engine_scelto = st.sidebar.selectbox("Game Engine (PREMIS)", ["Tutti"] + lista_engine)

lista_lingue = sorted({g["lingua"] for g in dati_completi if g["lingua"]})
lingua_scelta = st.sidebar.selectbox("Lingua (dc:language)", ["Tutte"] + lista_lingue)

formato_cercato = st.sidebar.text_input(
    "Contiene formato file (MODS)",
    placeholder="Es. .bik, .wav, .rim, .upk"
).strip().lower()

anni_presenti = [g["anno_num"] for g in dati_completi]
anno_min, anno_max = min(anni_presenti), max(anni_presenti)

if anno_min < anno_max:
    intervallo_anni = st.sidebar.slider(
        "Periodo di pubblicazione",
        min_value=anno_min,
        max_value=anno_max,
        value=(anno_min, anno_max)
    )
else:
    intervallo_anni = (anno_min, anno_max)

architettura_scelta = st.sidebar.radio("Architettura Eseguibile", ["Tutte", "32-bit", "64-bit"], horizontal=True)

st.sidebar.divider()

criterio_ordine = st.sidebar.selectbox(
    "Ordina risultati per",
    [
        "Titolo (A → Z)",
        "Anno di uscita (Più vecchi prima)",
        "Anno di uscita (Più recenti prima)",
        "Dimensione pacchetto (Più grandi prima)"
    ]
)

giochi_filtrati = []
for g in dati_completi:
    if testo_ricerca:
        testo_unito = f"{g['titolo']} {g['sviluppatore']} {g['valore_hash']} {g['id_gioco']} {g['eseguibile']}".lower()
        if testo_ricerca not in testo_unito:
            continue
    if dev_scelto != "Tutti" and g["sviluppatore"] != dev_scelto:
        continue
    if engine_scelto != "Tutti" and g["game_engine"] != engine_scelto:
        continue
    if lingua_scelta != "Tutte" and g["lingua"] != lingua_scelta:
        continue
    if formato_cercato:
        note = (g["note_formati"] or "").lower()
        if formato_cercato not in note:
            continue
    anno_inizio, anno_fine = intervallo_anni
    if not (anno_inizio <= g["anno_num"] <= anno_fine):
        continue
    if architettura_scelta != "Tutte":
        if not g["formato_binario"] or architettura_scelta not in g["formato_binario"]:
            continue
    giochi_filtrati.append(g)

if criterio_ordine == "Titolo (A → Z)":
    giochi_filtrati.sort(key=lambda x: x["titolo"].lower())
elif criterio_ordine == "Anno di uscita (Più vecchi prima)":
    giochi_filtrati.sort(key=lambda x: x["anno_num"])
elif criterio_ordine == "Anno di uscita (Più recenti prima)":
    giochi_filtrati.sort(key=lambda x: x["anno_num"], reverse=True)
elif criterio_ordine == "Dimensione pacchetto (Più grandi prima)":
    giochi_filtrati.sort(key=lambda x: x["dimensione_mb_num"], reverse=True)

peso_totale_gb = sum(g["dimensione_mb_num"] for g in giochi_filtrati) / 1024

col1, col2, col3, col4 = st.columns(4)
col1.metric("Titoli Filtrati", f"{len(giochi_filtrati)} / {len(dati_completi)}")
col2.metric("Volume Selezione", f"{peso_totale_gb:.2f} GB")
col3.metric("Motori Grafici", len({g["game_engine"] for g in giochi_filtrati if g["game_engine"]}))
col4.metric("Sviluppatori", len({g["sviluppatore"] for g in giochi_filtrati if g["sviluppatore"]}))

st.divider()

if not giochi_filtrati:
    st.warning("Nessun gioco corrisponde alla combinazione di filtri selezionata.")
else:
    st.subheader("Risultati della ricerca")
    tabella_vista = [
        {
            "ID Archivio": g["id_gioco"],
            "Titolo": g["titolo"],
            "Sviluppatore": g["sviluppatore"],
            "Data Uscita": g["data_rilascio"],
            "Lingua": g["lingua"],
            "Game Engine": g["game_engine"],
            "Dimensione": g["descrizione_fisica"]
        }
        for g in giochi_filtrati
    ]
    st.dataframe(tabella_vista, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Ispezione Scheda Archivistica Dettagliata")
    
    opzioni_selezione = {f"{g['titolo']} ({g['id_gioco']})": g for g in giochi_filtrati}
    etichetta_selezionata = st.selectbox("Seleziona un'opera per ispezionare tutti i metadati:", list(opzioni_selezione.keys()))
    gioco_sel = opzioni_selezione[etichetta_selezionata]

    tab_dc, tab_mods, tab_premis, tab_cr, tab_xml = st.tabs([
        "1. Dublin Core (Identificazione)",
        "2. MODS (Descrizione Fisica)",
        "3. PREMIS (Preservazione & Fixity)",
        "📋 Condition Report (Storico)",
        "📄 File XML Standard"
    ])

    with tab_dc:
        st.markdown(f"**Titolo (`dc:title`):** {gioco_sel['titolo']}")
        st.markdown(f"**Creatore (`dc:creator`):** {gioco_sel['sviluppatore']}")
        st.markdown(f"**Distributore / Copyright (`dc:publisher`):** {gioco_sel['publisher']}")
        st.markdown(f"**Data Pubblicazione (`dc:date`):** {gioco_sel['data_rilascio']}")
        st.markdown(f"**Lingua (`dc:language`):** {gioco_sel['lingua']}")
        st.markdown(f"**Identificativo (`dc:identifier`):** `{gioco_sel['id_gioco']}`")

    with tab_mods:
        st.markdown(f"**Edizione / Build (`mods:edition`):** {gioco_sel['versione_edizione'] or 'Non specificata'}")
        st.markdown(f"**Estensione Fisica (`mods:extent`):** {gioco_sel['descrizione_fisica']}")
        st.markdown(f"**Composizione Tecnica (`mods:note`):** {gioco_sel['note_formati']}")

    with tab_premis:
        st.markdown("#### Oggetto Digitale Preservato (`premis:object`)")
        st.markdown(f"**Percorso Eseguibile:** `{gioco_sel['eseguibile']}`")
        st.markdown(f"**Formato Binario:** {gioco_sel['formato_binario']}")
        st.markdown(f"**Dimensione Binario:** {gioco_sel['dim_exe_byte']:,} byte")
        st.code(f"{gioco_sel['algoritmo_hash']}: {gioco_sel['valore_hash']}", language="text")

        st.markdown("#### Ambiente ed Eventi di Preservazione (`premis:environment` / `premis:event`)")
        eventi = carica_eventi_gioco(gioco_sel["id_gioco"])
        for ev in eventi:
            st.info(f"**[{ev['categoria'].upper()}]** `{ev['tipo']}` — {ev['descrizione']} *(Registrato il: {ev['data_registrazione']})*")

    with tab_xml:
        file_xml_trovati = list(CARTELLA_XML.glob("*_archivio.xml"))
        contenuto_xml = None
        nome_file_xml = None
        for fx in file_xml_trovati:
            testo_temp = fx.read_text(encoding="utf-8")
            if gioco_sel["id_gioco"] in testo_temp:
                contenuto_xml = testo_temp
                nome_file_xml = fx.name
                break
        if contenuto_xml:
            st.download_button(
                label=f"⬇️ Scarica {nome_file_xml}",
                data=contenuto_xml,
                file_name=nome_file_xml,
                mime="application/xml"
            )
            st.code(contenuto_xml, language="xml")
        else:
            st.warning("File XML sorgente non trovato nella cartella output_xml.")

    with tab_cr:
        st.markdown("#### Registro Cronologico dei Controlli e delle Operazioni")
        reports = carica_condition_reports(gioco_sel["id_gioco"])

        if not reports:
            st.info("Nessun Condition Report registrato per questo oggetto. Esegui una sincronizzazione o un Fixity Audit.")
        else:
            for rep in reports:
                stato = rep["stato_integrita"]
                data_pulita = rep["data_ispezione"][:19].replace("T", " ")
                intestazione = f"**[{stato}]** `{rep['tipo_operazione']}` — *{data_pulita} UTC* (Agente: {rep['agente']})"
                
                dettaglio_manifest = ""
                if rep.get("manifest_riferimento"):
                    dettaglio_manifest = f"\n\n📄 **Manifest di riferimento:** `{rep['manifest_riferimento']}`"
                if rep.get("hash_rilevato"):
                    dettaglio_manifest += f" | **SHA-256:** `{rep['hash_rilevato'][:16]}...`"

                messaggio_completo = f"{intestazione}\n\n{rep['note_tecniche']}{dettaglio_manifest}"

                if stato == "INTACT":
                    st.success(messaggio_completo)
                elif stato in ("CORRUPTED", "MISSING"):
                    st.error(messaggio_completo)
                else:
                    st.warning(messaggio_completo)

        if MODALITA_LOCALE:
            st.divider()
            st.markdown("####Registra Nuova Operazione / Ispezione Manuale")
            with st.form(key=f"form_cr_{gioco_sel['id_gioco']}"):
                col_a, col_b = st.columns(2)
                tipo_op = col_a.selectbox(
                    "Tipo di Operazione",
                    ["Test di Esecuzione / Compatibilità", "Applicazione Patch / Wrapper", "Migrazione Supporto", "Ispezione Manuale"]
                )
                stato_op = col_b.selectbox(
                    "Stato Rilevato",
                    ["INTACT", "WARNING (Richiede Wrapper/Fix)", "CORRUPTED"]
                )
                agente_op = st.text_input("Curatore / Agente", value="Alessandro Mantoan (Archivista)")
                note_op = st.text_area("Note Tecniche e Osservazioni", placeholder="Es. Testato avvio su Windows 11: funzionamento regolare, audio e salvataggi ok.")
                
                invia = st.form_submit_button("Salva Condition Report")
                if invia:
                    if note_op.strip():
                        aggiungi_condition_report_manuale(gioco_sel["id_gioco"], tipo_op, agente_op, stato_op, note_op.strip())
                        st.success("Nuovo Condition Report registrato nello storico!")
                        st.rerun()
                    else:
                        st.warning("Inserisci una nota tecnica prima di salvare.")
