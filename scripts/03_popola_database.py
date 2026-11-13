import sqlite3
from pathlib import Path
from lxml import etree

BASE_DIR = Path(__file__).resolve().parent.parent

NS_ARCHIVIO = "http://" + "mioarchivio.local/schema/v1"
NS_DC = "http://" + "purl.org/dc/elements/1.1/"
NS_MODS = "http://" + "www.loc.gov/mods/v3"
NS_PREMIS = "http://" + "www.loc.gov/premis/v3"

NSMAP = {
    "archivio": NS_ARCHIVIO,
    "dc": NS_DC,
    "mods": NS_MODS,
    "premis": NS_PREMIS
}

def inizializza_database(percorso_db: Path):
    percorso_db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(percorso_db)
    cursore = conn.cursor()
    cursore.execute("PRAGMA foreign_keys = ON;")

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
        CREATE TABLE IF NOT EXISTS oggetti_digitali (
            id_oggetto INTEGER PRIMARY KEY AUTOINCREMENT,
            id_gioco TEXT NOT NULL,
            percorso_relativo TEXT NOT NULL,
            dimensione_byte INTEGER,
            algoritmo_hash TEXT,
            valore_hash TEXT UNIQUE,
            formato_binario TEXT,
            FOREIGN KEY (id_gioco) REFERENCES giochi (id_gioco) ON DELETE CASCADE
        );
    """)

    cursore.execute("""
        CREATE TABLE IF NOT EXISTS ambienti_eventi (
            id_record INTEGER PRIMARY KEY AUTOINCREMENT,
            id_gioco TEXT NOT NULL,
            categoria TEXT NOT NULL,
            tipo TEXT,
            descrizione TEXT,
            data_registrazione TEXT,
            FOREIGN KEY (id_gioco) REFERENCES giochi (id_gioco) ON DELETE CASCADE
        );
    """)

    conn.commit()
    conn.close()

def importa_xml_nel_db(file_xml: Path, file_db: Path):
    if not file_xml.exists():
        return

    inizializza_database(file_db)
    albero = etree.parse(str(file_xml))
    radice = albero.getroot()

    def estrai(xpath_query):
        risultato = radice.findtext(xpath_query, namespaces=NSMAP)
        return risultato.strip() if risultato else None

    id_gioco = estrai(".//dc:identifier")
    titolo = estrai(".//dc:title")
    sviluppatore = estrai(".//dc:creator")
    publisher = estrai(".//dc:publisher")
    data_rilascio = estrai(".//dc:date")
    lingua = estrai(".//dc:language")
    versione = estrai(".//mods:originInfo/mods:edition")
    estensione_fisica = estrai(".//mods:physicalDescription/mods:extent")
    note_formati = estrai(".//mods:note[@type='technical composition']")

    percorso_exe = estrai(".//premis:object/premis:objectIdentifier/premis:objectIdentifierValue")
    algoritmo_hash = estrai(".//premis:objectCharacteristics/premis:fixity/premis:messageDigestAlgorithm")
    valore_hash = estrai(".//premis:objectCharacteristics/premis:fixity/premis:messageDigest")
    dim_byte_str = estrai(".//premis:objectCharacteristics/premis:size")
    dim_byte = int(dim_byte_str) if dim_byte_str else 0
    formato_bin = estrai(".//premis:objectCharacteristics/premis:format/premis:formatDesignation/premis:formatName")

    conn = sqlite3.connect(file_db)
    cursore = conn.cursor()
    cursore.execute("PRAGMA foreign_keys = ON;")

    cursore.execute("DELETE FROM giochi WHERE id_gioco = ?;", (id_gioco,))

    cursore.execute("""
        INSERT INTO giochi (
            id_gioco, titolo, sviluppatore, publisher, data_rilascio,
            versione_edizione, lingua, descrizione_fisica, note_formati
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, (id_gioco, titolo, sviluppatore, publisher, data_rilascio, versione, lingua, estensione_fisica, note_formati))

    cursore.execute("""
        INSERT INTO oggetti_digitali (
            id_gioco, percorso_relativo, dimensione_byte, algoritmo_hash, valore_hash, formato_binario
        ) VALUES (?, ?, ?, ?, ?, ?);
    """, (id_gioco, percorso_exe, dim_byte, algoritmo_hash, valore_hash, formato_bin))

    for sw in radice.findall(".//premis:environment/premis:software", namespaces=NSMAP):
        nome_sw = sw.findtext("premis:swName", namespaces=NSMAP)
        tipo_sw = sw.findtext("premis:swType", namespaces=NSMAP)
        cursore.execute("""
            INSERT INTO ambienti_eventi (id_gioco, categoria, tipo, descrizione, data_registrazione)
            VALUES (?, 'software_environment', ?, ?, ?);
        """, (id_gioco, tipo_sw, nome_sw, data_rilascio))

    for ev in radice.findall(".//premis:event", namespaces=NSMAP):
        tipo_ev = ev.findtext("premis:eventType", namespaces=NSMAP)
        data_ev = ev.findtext("premis:eventDateTime", namespaces=NSMAP)
        dettaglio_ev = ev.findtext("premis:eventDetailInformation/premis:eventDetail", namespaces=NSMAP)
        categoria_ev = "preservation_planning" if dettaglio_ev else "preservation_event"
        cursore.execute("""
            INSERT INTO ambienti_eventi (id_gioco, categoria, tipo, descrizione, data_registrazione)
            VALUES (?, ?, ?, ?, ?);
        """, (id_gioco, categoria_ev, tipo_ev, dettaglio_ev, data_ev))

    # Estrae le Proprietà Significative (Significant Properties)
    for sig in radice.findall(".//premis:significantProperties", namespaces=NSMAP):
        tipo_sig = sig.findtext("premis:significantPropertiesType", namespaces=NSMAP) or "fidelity"
        val_sig = sig.findtext("premis:significantPropertiesValue", namespaces=NSMAP)
        if val_sig:
            cursore.execute("""
                INSERT INTO ambienti_eventi (id_gioco, categoria, tipo, descrizione, data_registrazione)
                VALUES (?, 'significant_properties', ?, ?, ?);
            """, (id_gioco, tipo_sig, val_sig, data_rilascio))

    # Estrae i Diritti e Licenze (PREMIS Rights)
    for rts in radice.findall(".//premis:rightsStatement", namespaces=NSMAP):
        termini = rts.findtext("premis:licenseInformation/premis:licenseTerms", namespaces=NSMAP)
        atti = rts.findtext("premis:rightsGranted/premis:act", namespaces=NSMAP) or "N/D"
        if termini:
            desc_diritti = f"{termini} [Azioni consentite: {atti}]"
            cursore.execute("""
                INSERT INTO ambienti_eventi (id_gioco, categoria, tipo, descrizione, data_registrazione)
                VALUES (?, 'rights_management', 'license', ?, ?);
            """, (id_gioco, desc_diritti, data_rilascio))

    conn.commit()
    conn.close()
    print(f"Importato nel DB: '{titolo}' ({id_gioco})")

if __name__ == "__main__":
    CARTELLA_XML_INPUT = BASE_DIR / "output_xml"
    FILE_DATABASE = BASE_DIR / "database" / "archivio_giochi.db"
    
    tutti_gli_xml = list(CARTELLA_XML_INPUT.glob("*_archivio.xml"))
    print(f"Trovati {len(tutti_gli_xml)} file XML da importare nel database...")
    
    for f_xml in tutti_gli_xml:
        importa_xml_nel_db(f_xml, FILE_DATABASE)
