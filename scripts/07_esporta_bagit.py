import sys
import json
import shutil
import hashlib
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

BASE_DIR = Path(__file__).resolve().parent.parent

def calcola_sha256(percorso_file: Path) -> str:
    hasher = hashlib.sha256()
    with open(percorso_file, "rb") as f:
        while blocco := f.read(1048576):
            hasher.update(blocco)
    return hasher.hexdigest()

def carica_esclusioni(percorso_config: Path) -> tuple:
    if not percorso_config.exists():
        return set(), set()
    with open(percorso_config, "r", encoding="utf-8") as f:
        dati = json.load(f)
    cartelle = {c.lower() for c in dati.get("cartelle_escluse", [])}
    estensioni = {e.lower() for e in dati.get("estensioni_escluse", [])}
    return cartelle, estensioni

def file_da_ignorare(percorso_file: Path, radice_gioco: Path, cartelle_escluse: set, estensioni_escluse: set) -> bool:
    if percorso_file.suffix.lower() in estensioni_escluse:
        return True
    parti_relative = {p.lower() for p in percorso_file.relative_to(radice_gioco).parts[:-1]}
    return bool(parti_relative.intersection(cartelle_escluse))

def esporta_storico_condition_reports(db_path: Path, id_gioco_completo: str, dest_json: Path):
    if not db_path.exists():
        return
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursore = conn.cursor()
    cursore.execute("""
        SELECT id_report, data_ispezione, tipo_operazione, agente,
               stato_integrita, manifest_riferimento, hash_rilevato, note_tecniche
        FROM condition_reports
        WHERE id_gioco = ?
        ORDER BY data_ispezione ASC;
    """, (id_gioco_completo,))
    rows = [dict(r) for r in cursore.fetchall()]
    conn.close()

    with open(dest_json, "w", encoding="utf-8") as f:
        json.dump({"id_gioco": id_gioco_completo, "condition_reports": rows}, f, indent=2, ensure_ascii=False)

def crea_pacchetto_bagit(nome_cartella_gioco: str):
    file_settings = BASE_DIR / "config" / "settings.json"
    if not file_settings.exists():
        print("ERRORE: config/settings.json non trovato.")
        return

    with open(file_settings, "r", encoding="utf-8") as f:
        settings = json.load(f)

    cartella_libreria = Path(settings.get("gog_library_path", ""))
    cartella_gioco = cartella_libreria / nome_cartella_gioco

    if not cartella_gioco.exists():
        print(f"ERRORE: Gioco '{nome_cartella_gioco}' non trovato in '{cartella_libreria}'.")
        return

    nome_pulito = nome_cartella_gioco.replace(" ", "_")
    cartella_aip = BASE_DIR / "output_aip" / f"{nome_pulito}_AIP"
    cartella_data = cartella_aip / "data"
    cartella_game_payload = cartella_data / "game_files"
    cartella_meta_payload = cartella_data / "archival_metadata"

    if cartella_aip.exists():
        shutil.rmtree(cartella_aip)

    cartella_game_payload.mkdir(parents=True, exist_ok=True)
    cartella_meta_payload.mkdir(parents=True, exist_ok=True)

    print(f"Creazione pacchetto AIP BagIt (RFC 8493) per: {nome_cartella_gioco}...")

    # 1. Carica eventuale manifest SHA-256 gia calcolato per evitare ricalcoli inutili
    file_manifest_json = BASE_DIR / "output_json" / f"{nome_pulito}_manifest_sha256.json"
    hash_precalcolati = {}
    id_gioco_completo = ""
    if file_manifest_json.exists():
        with open(file_manifest_json, "r", encoding="utf-8") as fm:
            dati_m = json.load(fm)
            id_gioco_completo = dati_m.get("gog_game_id", "")
            for rel_p, info in dati_m.get("files", {}).items():
                hash_precalcolati[rel_p] = info.get("sha256")

    # 2. Copia i file del gioco escludendo i salvataggi utente
    cartelle_escl, estensioni_escl = carica_esclusioni(BASE_DIR / "config" / "esclusioni_audit.json")
    righe_manifest = []
    totale_byte = 0
    totale_file = 0

    print("Copia dei binari originali in data/game_files/...")
    for f in cartella_gioco.rglob("*"):
        if f.is_file() and not file_da_ignorare(f, cartella_gioco, cartelle_escl, estensioni_escl):
            rel_path = f.relative_to(cartella_gioco)
            rel_str_unix = str(rel_path).replace("\\", "/")
            dest_file = cartella_game_payload / rel_path
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest_file)

            sha = hash_precalcolati.get(rel_str_unix) or calcola_sha256(dest_file)
            righe_manifest.append(f"{sha}  data/game_files/{rel_str_unix}")
            totale_byte += dest_file.stat().st_size
            totale_file += 1

    # 3. Copia i metadati archivistici (XML DC/MODS/PREMIS, JSON, Condition Reports)
    print("Inclusione metadati DC/MODS/PREMIS e storico Condition Reports...")
    file_xml = BASE_DIR / "output_xml" / f"{nome_pulito}_archivio.xml"
    file_json = BASE_DIR / "output_json" / f"{nome_pulito}_modulo1.json"

    for f_meta in [file_xml, file_json, file_manifest_json]:
        if f_meta.exists():
            dest_m = cartella_meta_payload / f_meta.name
            shutil.copy2(f_meta, dest_m)
            sha_m = calcola_sha256(dest_m)
            righe_manifest.append(f"{sha_m}  data/archival_metadata/{f_meta.name}")
            totale_byte += dest_m.stat().st_size
            totale_file += 1

    if id_gioco_completo:
        dest_cr = cartella_meta_payload / f"{nome_pulito}_condition_reports.json"
        esporta_storico_condition_reports(BASE_DIR / "database" / "archivio_giochi.db", id_gioco_completo, dest_cr)
        if dest_cr.exists():
            sha_cr = calcola_sha256(dest_cr)
            righe_manifest.append(f"{sha_cr}  data/archival_metadata/{dest_cr.name}")
            totale_byte += dest_cr.stat().st_size
            totale_file += 1

    # 4. Scrive bagit.txt (RFC 8493)
    file_bagit_txt = cartella_aip / "bagit.txt"
    file_bagit_txt.write_text("BagIt-Version: 1.0\nTag-File-Character-Encoding: UTF-8\n", encoding="utf-8")

    # 5. Scrive bag-info.txt
    data_oggi = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dim_mb = round(totale_byte / (1024 * 1024), 2)
    contenuto_bag_info = (
        f"Source-Organization: Archivio Privato Preservazione Videogiochi\n"
        f"Bagging-Date: {data_oggi}\n"
        f"External-Identifier: {id_gioco_completo or nome_pulito}\n"
        f"Payload-Oxum: {totale_byte}.{totale_file}\n"
        f"Bag-Size: {dim_mb} MB\n"
    )
    file_bag_info = cartella_aip / "bag-info.txt"
    file_bag_info.write_text(contenuto_bag_info, encoding="utf-8")

    # 6. Scrive manifest-sha256.txt
    file_manifest_txt = cartella_aip / "manifest-sha256.txt"
    file_manifest_txt.write_text("\n".join(sorted(righe_manifest)) + "\n", encoding="utf-8")

    # 7. Scrive tagmanifest-sha256.txt (sigillo di integrita sui tag file)
    righe_tag = []
    for tag_f in [file_bagit_txt, file_bag_info, file_manifest_txt]:
        righe_tag.append(f"{calcola_sha256(tag_f)}  {tag_f.name}")
    file_tagmanifest = cartella_aip / "tagmanifest-sha256.txt"
    file_tagmanifest.write_text("\n".join(righe_tag) + "\n", encoding="utf-8")

    print(f"\nPacchetto BagIt AIP completato con successo in:\n{cartella_aip}")
    print(f"Totale file sigillati: {totale_file} ({dim_mb} MB)")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: py scripts/07_esporta_bagit.py \"Nome Cartella Gioco\"")
        print("Esempio: py scripts/07_esporta_bagit.py \"Stronghold Crusader Extreme HD\"")
        sys.exit(1)

    crea_pacchetto_bagit(sys.argv[1])
