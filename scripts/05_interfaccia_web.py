import re
import sys
import sqlite3
import subprocess
from pathlib import Path
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent.parent

st.set_page_config(
    page_title="Archivio Digitale Videogiochi",
    page_icon="🕹️",
    layout="wide"
)

PERCORSO_DB = BASE_DIR / "database" / "archivio_giochi.db"
CARTELLA_XML = BASE_DIR / "output_xml"
CARTELLA_SCRIPTS = BASE_DIR / "scripts"

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

st.title("🕹️ Archivio di Preservazione Digitale — Videogiochi")
st.markdown("Catalogo basato sugli standard internazionali **Dublin Core**, **MODS** e **PREMIS**.")

st.sidebar.header("🔍 Ricerca e Filtri Avanzati")

if st.sidebar.button("🔄 Sincronizza Libreria GOG", use_container_width=True):
    with st.spinner("Scansione cartelle GOG, generazione XML e aggiornamento database in corso..."):
        subprocess.run([sys.executable, str(CARTELLA_SCRIPTS / "01_estrattore_gog.py")], check=True)
        subprocess.run([sys.executable, str(CARTELLA_SCRIPTS / "02_generatore_xml.py")], check=True)
        subprocess.run([sys.executable, str(CARTELLA_SCRIPTS / "03_popola_database.py")], check=True)
    st.success("Archivio aggiornato con successo!")
    st.rerun()

st.sidebar.divider()

dati_completi = carica_dati_archivio()

if not dati_completi:
    st.warning("Il database è attualmente vuoto o non ancora creato. Clicca su **'🔄 Sincronizza Libreria GOG'** nella barra laterale (assicurati di aver configurato `config/settings.json`).")
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
    st.subheader("📋 Risultati della ricerca")
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
    st.subheader("🗂️ Ispezione Scheda Archivistica Dettagliata")
    
    opzioni_selezione = {f"{g['titolo']} ({g['id_gioco']})": g for g in giochi_filtrati}
    etichetta_selezionata = st.selectbox("Seleziona un'opera per ispezionare tutti i metadati:", list(opzioni_selezione.keys()))
    gioco_sel = opzioni_selezione[etichetta_selezionata]

    tab_dc, tab_mods, tab_premis, tab_xml = st.tabs([
        "1. Dublin Core (Identificazione)",
        "2. MODS (Descrizione Fisica)",
        "3. PREMIS (Preservazione & Fixity)",
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
