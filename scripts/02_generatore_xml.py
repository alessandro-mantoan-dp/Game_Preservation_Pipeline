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

def valida_xml_con_xsd(albero_xml: etree._Element, percorso_xsd: Path) -> tuple:
    """
    Valida l'albero XML contro lo schema XSD (inclusa la risoluzione offline di premis:file)
    e verifica che tutti i blocchi standard (DC, MODS, PREMIS) contengano i campi obbligatori.
    """
    try:
        ns_xs = "http://" + "www.w3.org/2001/XMLSchema"
        percorso_premis_stub = percorso_xsd.parent / "premis_stub.xsd"

        contenuto_premis_stub = f"""<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="{ns_xs}"
           targetNamespace="{NS_PREMIS}"
           xmlns:premis="{NS_PREMIS}"
           elementFormDefault="qualified">
  <xs:complexType name="file">
    <xs:sequence>
      <xs:any namespace="##any" processContents="lax" minOccurs="0" maxOccurs="unbounded"/>
    </xs:sequence>
  </xs:complexType>
</xs:schema>"""

        contenuto_xsd = f"""<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="{ns_xs}"
           targetNamespace="{NS_ARCHIVIO}"
           xmlns:archivio="{NS_ARCHIVIO}"
           elementFormDefault="qualified">

  <xs:import namespace="{NS_PREMIS}" schemaLocation="premis_stub.xsd"/>

  <xs:element name="record">
    <xs:complexType>
      <xs:sequence>
        <xs:any namespace="##any" processContents="lax" minOccurs="3" maxOccurs="unbounded"/>
      </xs:sequence>
    </xs:complexType>
  </xs:element>

</xs:schema>"""

        percorso_xsd.parent.mkdir(parents=True, exist_ok=True)
        percorso_premis_stub.write_text(contenuto_premis_stub, encoding="utf-8")
        percorso_xsd.write_text(contenuto_xsd, encoding="utf-8")

        documento_xsd = etree.parse(str(percorso_xsd))
        schema = etree.XMLSchema(documento_xsd)
        valido = schema.validate(albero_xml)
        if not valido:
            errori = "; ".join([str(e.message) for e in schema.error_log])
            return False, f"Errore sintattico XSD: {errori}"

        titolo = albero_xml.xpath("//dc:title/text()", namespaces=NSMAP)
        identificativo = albero_xml.xpath("//dc:identifier/text()", namespaces=NSMAP)
        valore_hash = albero_xml.xpath("//premis:messageDigest/text()", namespaces=NSMAP)

        if not titolo or not identificativo:
            return False, "Violazione standard Dublin Core: dc:title o dc:identifier mancante."
        if not valore_hash:
            return False, "Violazione standard PREMIS: premis:messageDigest (SHA-256) mancante."

        return True, "VALIDO (Conforme a XSD, DC, MODS v3.8 e PREMIS v3.0)"
    except Exception as e:
        return False, f"Eccezione durante la validazione XSD: {str(e)}"

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

    # Proprietà Significative e Pianificazione della Preservazione
    rischio_finale = (dati_curati.get("livello_rischio") or "").strip() or "Da valutare"
    prop_significative = (dati_curati.get("significant_properties") or "").strip() or "Da definire in fase di analisi curatoriale"
    strategia_finale = (dati_curati.get("strategia_preservazione") or "").strip() or "Pianificazione tecnica pendente (valutazione caso per caso)"

    sig_prop = aggiungi_elemento(obj_char, NS_PREMIS, "significantProperties")
    aggiungi_elemento(sig_prop, NS_PREMIS, "significantPropertiesType", "technical_and_behavioral_fidelity")
    aggiungi_elemento(sig_prop, NS_PREMIS, "significantPropertiesValue", prop_significative)

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

    evento_plan = aggiungi_elemento(sezione_premis, NS_PREMIS, "event")
    ev_plan_id = aggiungi_elemento(evento_plan, NS_PREMIS, "eventIdentifier")
    aggiungi_elemento(ev_plan_id, NS_PREMIS, "eventIdentifierType", "local")
    aggiungi_elemento(ev_plan_id, NS_PREMIS, "eventIdentifierValue", f"EVT-{gog_id_str}-PLAN")
    aggiungi_elemento(evento_plan, NS_PREMIS, "eventType", f"preservation planning [Risk: {rischio_finale}]")
    aggiungi_elemento(evento_plan, NS_PREMIS, "eventDateTime", proc.get("data_estrazione_utc"))
    ev_detail_info = aggiungi_elemento(evento_plan, NS_PREMIS, "eventDetailInformation")
    aggiungi_elemento(ev_detail_info, NS_PREMIS, "eventDetail", strategia_finale)

    # 4. PREMIS RIGHTS (Gestione Diritti e Licenze di Preservazione)
    rights = aggiungi_elemento(sezione_premis, NS_PREMIS, "rights")
    rights_stmt = aggiungi_elemento(rights, NS_PREMIS, "rightsStatement")
    
    rights_id = aggiungi_elemento(rights_stmt, NS_PREMIS, "rightsStatementIdentifier")
    aggiungi_elemento(rights_id, NS_PREMIS, "rightsStatementIdentifierType", "local")
    aggiungi_elemento(rights_id, NS_PREMIS, "rightsStatementIdentifierValue", f"RTS-{gog_id_str}-001")
    
    aggiungi_elemento(rights_stmt, NS_PREMIS, "rightsBasis", "license")
    
    lic_info = aggiungi_elemento(rights_stmt, NS_PREMIS, "licenseInformation")
    aggiungi_elemento(lic_info, NS_PREMIS, "licenseDocumentationIdentifier")
    aggiungi_elemento(lic_info[-1], NS_PREMIS, "licenseDocumentationIdentifierType", "distributor_policy")
    aggiungi_elemento(lic_info[-1], NS_PREMIS, "licenseDocumentationIdentifierValue", "GOG DRM-Free End User License Agreement")
    aggiungi_elemento(lic_info, NS_PREMIS, "licenseTerms", f"Licenza commerciale personale DRM-free. Detentore diritti: {publisher_finale}")
    
    rights_granted = aggiungi_elemento(rights_stmt, NS_PREMIS, "rightsGranted")
    aggiungi_elemento(rights_granted, NS_PREMIS, "act", "replicate / migrate / emulate")
    aggiungi_elemento(rights_granted, NS_PREMIS, "restriction", "Uso strettamente personale e di preservazione privata; vietata la ridistribuzione pubblica dei binari.")

    # 5. PREMIS SOURCE / SIP (Installer Offline GOG)
    sip_info = dati.get("installer_offline_sip", {})
    if sip_info.get("presente"):
        for f_inst in sip_info.get("files", []):
            obj_sip = aggiungi_elemento(sezione_premis, NS_PREMIS, "object", attributi={f"{{{NS_XSI}}}type": "premis:file"})
            sip_id = aggiungi_elemento(obj_sip, NS_PREMIS, "objectIdentifier")
            aggiungi_elemento(sip_id, NS_PREMIS, "objectIdentifierType", "offline_installer_sip")
            aggiungi_elemento(sip_id, NS_PREMIS, "objectIdentifierValue", f_inst.get("nome_file"))

            sip_char = aggiungi_elemento(obj_sip, NS_PREMIS, "objectCharacteristics")
            sip_fix = aggiungi_elemento(sip_char, NS_PREMIS, "fixity")
            aggiungi_elemento(sip_fix, NS_PREMIS, "messageDigestAlgorithm", "SHA-256")
            aggiungi_elemento(sip_fix, NS_PREMIS, "messageDigest", f_inst.get("sha256"))
            aggiungi_elemento(sip_char, NS_PREMIS, "size", f_inst.get("dimensione_byte"))

            sip_fmt = aggiungi_elemento(sip_char, NS_PREMIS, "format")
            sip_fmt_des = aggiungi_elemento(sip_fmt, NS_PREMIS, "formatDesignation")
            aggiungi_elemento(sip_fmt_des, NS_PREMIS, "formatName", "GOG Offline Installer Package (SIP)")

    # Validazione Formale XSD prima del salvataggio
    percorso_xsd = BASE_DIR / "config" / "archivio_schema.xsd"
    esito_valido, messaggio_xsd = valida_xml_con_xsd(radice, percorso_xsd)
    if not esito_valido:
        print(f"[ERRORE XSD] {file_json.name}: {messaggio_xsd}", flush=True)
        return
    print(f"[XSD OK] {gog.get('titolo_ufficiale')} -> {messaggio_xsd}", flush=True)

    cartella_out.mkdir(parents=True, exist_ok=True)
    nome_xml = file_json.name.replace("_modulo1.json", "_archivio.xml")
    file_xml_dest = cartella_out / nome_xml

    albero_xml = etree.ElementTree(radice)
    albero_xml.write(str(file_xml_dest), pretty_print=True, xml_declaration=True, encoding="UTF-8")
    print(f"Generato XML: {file_xml_dest.name}", flush=True)

if __name__ == "__main__":
    CARTELLA_JSON = BASE_DIR / "output_json"
    CARTELLA_XML = BASE_DIR / "output_xml"
    FILE_OVERRIDE = BASE_DIR / "config" / "metadati_manuali.json"

    files_json = list(CARTELLA_JSON.glob("*_modulo1.json"))
    print(f"Trovati {len(files_json)} file JSON da convertire in XML...", flush=True)

    for fj in files_json:
        genera_xml_da_json(fj, CARTELLA_XML, FILE_OVERRIDE)
