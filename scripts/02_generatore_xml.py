import json
from pathlib import Path
from lxml import etree

BASE_DIR = Path(__file__).resolve().parent.parent

NS_ARCHIVIO = "http://" + "mioarchivio.local/schema/v1"
NS_DC = "http://" + "purl.org/dc/elements/1.1/"
NS_MODS = "http://" + "www.loc.gov/mods/v3"
NS_PREMIS = "http://" + "www.loc.gov/premis/v3"
NS_XSI = "http://" + "www.w3.org/2001/XMLSchema-instance"

NSMAP = {
    "archivio": NS_ARCHIVIO,
    "dc": NS_DC,
    "mods": NS_MODS,
    "premis": NS_PREMIS,
    "xsi": NS_XSI
}

def aggiungi_elemento(genitore, namespace, nome_tag, testo=None, attributi=None):
    tag_completo = f"{{{namespace}}}{nome_tag}"
    elemento = etree.SubElement(genitore, tag_completo, attrib=attributi or {})
    if testo is not None:
        elemento.text = str(testo)
    return elemento

def carica_override_manuali(percorso_override: Path) -> dict:
    if percorso_override.exists():
        with open(percorso_override, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def genera_xml_da_json(file_json: Path, cartella_out: Path, file_override: Path):
    if not file_json.exists():
        return

    with open(file_json, "r", encoding="utf-8") as f:
        dati = json.load(f)

    proc = dati["metadati_processo"]
    gog = dati["identificazione_gog"]
    stat = dati["statistiche_pacchetto"]
    exe = dati["analisi_eseguibile_principale"]
    pe = exe["pe_header"]
    meta_pe = pe.get("metadati_interni", {})
    amb = dati["ambiente_tecnico"]

    overrides = carica_override_manuali(file_override)
    gog_id_str = str(gog.get("gog_game_id", ""))
    dati_curati = overrides.get(gog_id_str, {})

    sviluppatore_finale = dati_curati.get("creator") or meta_pe.get("CompanyName") or "Sconosciuto"
    publisher_finale = dati_curati.get("publisher") or ("GOG.com (Distributore) / " + meta_pe.get("LegalCopyright", ""))
    data_storica_finale = dati_curati.get("date") or pe.get("data_compilazione_utc", "")[:10]

    radice = etree.Element(f"{{{NS_ARCHIVIO}}}record", nsmap=NSMAP)

    # 1. DUBLIN CORE
    sezione_dc = aggiungi_elemento(radice, NS_DC, "metadata")
    aggiungi_elemento(sezione_dc, NS_DC, "title", gog.get("titolo_ufficiale"))
    aggiungi_elemento(sezione_dc, NS_DC, "creator", sviluppatore_finale)
    aggiungi_elemento(sezione_dc, NS_DC, "publisher", publisher_finale)
    aggiungi_elemento(sezione_dc, NS_DC, "date", data_storica_finale)
    aggiungi_elemento(sezione_dc, NS_DC, "type", "Software / Video Game")
    aggiungi_elemento(sezione_dc, NS_DC, "format", "Digital Download (DRM-Free)")
    aggiungi_elemento(sezione_dc, NS_DC, "identifier", f"GOG-{gog_id_str}")
    aggiungi_elemento(sezione_dc, NS_DC, "language", gog.get("lingua"))

    # 2. MODS
    sezione_mods = aggiungi_elemento(radice, NS_MODS, "mods", attributi={"version": "3.8"})
    title_info = aggiungi_elemento(sezione_mods, NS_MODS, "titleInfo")
    aggiungi_elemento(title_info, NS_MODS, "title", gog.get("titolo_ufficiale"))

    if sviluppatore_finale != "Sconosciuto":
        name_node = aggiungi_elemento(sezione_mods, NS_MODS, "name", attributi={"type": "corporate"})
        aggiungi_elemento(name_node, NS_MODS, "namePart", sviluppatore_finale)
        role_node = aggiungi_elemento(name_node, NS_MODS, "role")
        aggiungi_elemento(role_node, NS_MODS, "roleTerm", "developer", attributi={"type": "text"})

    origin_info = aggiungi_elemento(sezione_mods, NS_MODS, "originInfo")
    aggiungi_elemento(origin_info, NS_MODS, "dateIssued", data_storica_finale, attributi={"encoding": "iso8601"})
    aggiungi_elemento(origin_info, NS_MODS, "dateCreated", pe.get("data_compilazione_utc"), attributi={"encoding": "iso8601"})
    if meta_pe.get("ProductVersion"):
        aggiungi_elemento(origin_info, NS_MODS, "edition", f"Version {meta_pe['ProductVersion']}")

    phys_desc = aggiungi_elemento(sezione_mods, NS_MODS, "physicalDescription")
    aggiungi_elemento(phys_desc, NS_MODS, "digitalOrigin", "born digital")
    aggiungi_elemento(phys_desc, NS_MODS, "extent", f"{stat['numero_totale_file']} files ({stat['dimensione_totale_mb']} MB)")

    tutti_formati = stat["distribuzione_formati"].items()
    testo_formati = ", ".join([f"{ext} ({count})" for ext, count in tutti_formati])
    aggiungi_elemento(sezione_mods, NS_MODS, "note", f"File formats composition: {testo_formati}", attributi={"type": "technical composition"})

    # 3. PREMIS
    sezione_premis = aggiungi_elemento(radice, NS_PREMIS, "premis", attributi={"version": "3.0"})
    obj = aggiungi_elemento(sezione_premis, NS_PREMIS, "object", attributi={f"{{{NS_XSI}}}type": "premis:file"})
    
    obj_id = aggiungi_elemento(obj, NS_PREMIS, "objectIdentifier")
    aggiungi_elemento(obj_id, NS_PREMIS, "objectIdentifierType", "relative_path")
    aggiungi_elemento(obj_id, NS_PREMIS, "objectIdentifierValue", exe.get("percorso_relativo"))

    obj_char = aggiungi_elemento(obj, NS_PREMIS, "objectCharacteristics")
    fixity = aggiungi_elemento(obj_char, NS_PREMIS, "fixity")
    aggiungi_elemento(fixity, NS_PREMIS, "messageDigestAlgorithm", "SHA-256")
    aggiungi_elemento(fixity, NS_PREMIS, "messageDigest", exe.get("sha256"))
    aggiungi_elemento(obj_char, NS_PREMIS, "size", exe.get("dimensione_byte"))
    
    fmt = aggiungi_elemento(obj_char, NS_PREMIS, "format")
    fmt_des = aggiungi_elemento(fmt, NS_PREMIS, "formatDesignation")
    aggiungi_elemento(fmt_des, NS_PREMIS, "formatName", f"Windows Portable Executable ({pe.get('architettura')})")

    env = aggiungi_elemento(sezione_premis, NS_PREMIS, "environment")
    aggiungi_elemento(env, NS_PREMIS, "environmentCharacteristic", "known to work")
    aggiungi_elemento(env, NS_PREMIS, "environmentPurpose", "render / execute")
    
    sw_engine = aggiungi_elemento(env, NS_PREMIS, "software")
    aggiungi_elemento(sw_engine, NS_PREMIS, "swName", amb.get("game_engine"))
    aggiungi_elemento(sw_engine, NS_PREMIS, "swType", "game engine")

    sw_os = aggiungi_elemento(env, NS_PREMIS, "software")
    aggiungi_elemento(sw_os, NS_PREMIS, "swName", f"Windows ({pe.get('architettura')}) - Wrapper: {amb.get('ambiente_esecuzione')}")
    aggiungi_elemento(sw_os, NS_PREMIS, "swType", "operating environment")

    evento = aggiungi_elemento(sezione_premis, NS_PREMIS, "event")
    ev_id = aggiungi_elemento(evento, NS_PREMIS, "eventIdentifier")
    aggiungi_elemento(ev_id, NS_PREMIS, "eventIdentifierType", "local")
    aggiungi_elemento(ev_id, NS_PREMIS, "eventIdentifierValue", f"EVT-{gog_id_str}-001")
    aggiungi_elemento(evento, NS_PREMIS, "eventType", "metadata extraction and fixity calculation")
    aggiungi_elemento(evento, NS_PREMIS, "eventDateTime", proc.get("data_estrazione_utc"))
    
    ev_detail = aggiungi_elemento(evento, NS_PREMIS, "eventDetailInformation")
    aggiungi_elemento(ev_detail, NS_PREMIS, "eventDetail", f"Engine identified via: {amb.get('metodo_rilevamento_engine')}")

    cartella_out.mkdir(parents=True, exist_ok=True)
    nome_xml = file_json.stem.replace("_modulo1", "_archivio.xml")
    file_destinazione = cartella_out / nome_xml

    albero_xml = etree.ElementTree(radice)
    albero_xml.write(str(file_destinazione), pretty_print=True, xml_declaration=True, encoding="UTF-8")
    print(f"Generato XML: {file_destinazione.name}")

if __name__ == "__main__":
    CARTELLA_JSON_INPUT = BASE_DIR / "output_json"
    CARTELLA_XML_OUTPUT = BASE_DIR / "output_xml"
    FILE_OVERRIDE = BASE_DIR / "config" / "metadati_manuali.json"
    
    tutti_i_json = list(CARTELLA_JSON_INPUT.glob("*_modulo1.json"))
    print(f"Trovati {len(tutti_i_json)} file JSON da convertire in XML...")
    
    for f_json in tutti_i_json:
        genera_xml_da_json(f_json, CARTELLA_XML_OUTPUT, FILE_OVERRIDE)
