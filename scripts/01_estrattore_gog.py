import json
import sys
import sqlite3
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from esporta_reports import aggiorna_file_condition_report
from collections import Counter
import pefile

# Calcola dinamicamente la cartella radice del progetto (risale da scripts/ alla cartella principale)
BASE_DIR = Path(__file__).resolve().parent.parent

def calcola_sha256(percorso_file: Path) -> str:
    hasher = hashlib.sha256()
    with open(percorso_file, 'rb') as f:
        while blocco := f.read(1048576):
            hasher.update(blocco)
    return hasher.hexdigest()

def leggi_manifest_gog(cartella_radice: Path) -> dict:
    file_info = list(cartella_radice.glob("goggame-*.info"))
    if not file_info:
        return {"trovato": False, "messaggio": "Nessun file .info di GOG trovato nella radice"}

    with open(file_info[0], "r", encoding="utf-8") as f:
        dati_grezzi = json.load(f)

    eseguibile_ufficiale = None
    argomenti_avvio = None
    for task in dati_grezzi.get("playTasks", []):
        if task.get("isPrimary"):
            eseguibile_ufficiale = task.get("path")
            argomenti_avvio = task.get("arguments", "")
            break

    return {
        "trovato": True,
        "file_sorgente": file_info[0].name,
        "gog_game_id": dati_grezzi.get("gameId"),
        "titolo_ufficiale": dati_grezzi.get("name"),
        "lingua": dati_grezzi.get("language"),
        "eseguibile_dichiarato": eseguibile_ufficiale,
        "argomenti_avvio": argomenti_avvio
    }

def ispeziona_header_pe(percorso_exe: Path) -> dict:
    if not percorso_exe or not percorso_exe.exists():
        return {"errore": "File eseguibile non trovato sul disco"}

    risultato = {
        "architettura": "Sconosciuta",
        "data_compilazione_utc": None,
        "metadati_interni": {}
    }

    try:
        pe = pefile.PE(str(percorso_exe))
        macchina = pe.FILE_HEADER.Machine
        if macchina == 0x8664:
            risultato["architettura"] = "x64 (64-bit)"
        elif macchina == 0x14c:
            risultato["architettura"] = "x86 (32-bit)"

        timestamp = pe.FILE_HEADER.TimeDateStamp
        data_comp = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        risultato["data_compilazione_utc"] = data_comp.isoformat()

        if hasattr(pe, 'FileInfo'):
            for file_info in pe.FileInfo:
                for entry in file_info:
                    if hasattr(entry, 'StringTable'):
                        for st in entry.StringTable:
                            for k, v in st.entries.items():
                                chiave = k.decode('utf-8', errors='ignore').strip()
                                valore = v.decode('utf-8', errors='ignore').strip()
                                if valore:
                                    risultato["metadati_interni"][chiave] = valore
        pe.close()
    except Exception as e:
        risultato["errore"] = f"Impossibile leggere PE Header: {str(e)}"

    return risultato

def carica_dizionario_firme(percorso_config: Path) -> dict:
    if not percorso_config.exists():
        return {"librerie_chiave": {}, "estensioni_chiave": {}}
    with open(percorso_config, "r", encoding="utf-8") as f:
        return json.load(f)

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

def cerca_installer_offline(cartella_installers: Path, titolo_gioco: str, nome_cartella: str) -> list:
    """
    Cerca i file dell'installer offline GOG (setup_*.exe e *.bin) associati al gioco,
    calcolandone dimensione e impronta SHA-256.
    """
    if not cartella_installers or not cartella_installers.exists():
        return []

    chiavi_ricerca = {
        titolo_gioco.lower().replace(":", "").replace("-", " ").strip(),
        nome_cartella.lower().replace("_", " ").replace("-", " ").strip()
    }
    chiavi_pulite = {
        "".join(c for c in k if c.isalnum()) for k in chiavi_ricerca if k
    }

    file_trovati = []
    for elemento in cartella_installers.rglob("*"):
        if not elemento.is_file():
            continue
        est = elemento.suffix.lower()
        if est not in (".exe", ".bin"):
            continue
        if est == ".exe" and not elemento.name.lower().startswith("setup_"):
            continue

        percorso_norm = "".join(c for c in str(elemento.relative_to(cartella_installers)).lower() if c.isalnum())
        if any(chiave in percorso_norm for chiave in chiavi_pulite if len(chiave) >= 5):
            file_trovati.append(elemento)

    risultati = []
    for f_inst in sorted(file_trovati, key=lambda x: x.name):
        print(f"   Trovato installer offline: {f_inst.name} (calcolo SHA-256)...", flush=True)
        risultati.append({
            "nome_file": f_inst.name,
            "percorso_relativo": str(f_inst.relative_to(cartella_installers)).replace("\\", "/"),
            "dimensione_byte": f_inst.stat().st_size,
            "sha256": calcola_sha256(f_inst)
        })
    return risultati

def rileva_tecnologie(lista_file: list, conteggio_estensioni: Counter, percorso_config: Path) -> dict:
    regole = carica_dizionario_firme(percorso_config)
    nomi_minuscoli = {f.name.lower() for f in lista_file}
    estensioni_presenti = set(conteggio_estensioni.keys())
    
    engine = "Sconosciuto / Proprietario"
    metodo_rilevamento = "Nessuno"

    for firma_file, nome_engine in regole.get("librerie_chiave", {}).items():
        if any(firma_file.lower() in nome for nome in nomi_minuscoli):
            engine = nome_engine
            metodo_rilevamento = f"Libreria rilevata ({firma_file})"
            break

    if engine == "Sconosciuto / Proprietario":
        for nome_engine, lista_ext in regole.get("estensioni_chiave", {}).items():
            if set(lista_ext).issubset(estensioni_presenti):
                engine = nome_engine
                metodo_rilevamento = f"Firme estensioni ({', '.join(lista_ext)})"
                break

    wrapper_emulazione = "Nessuno (Nativo Windows)"
    if "dosbox.exe" in nomi_minuscoli:
        wrapper_emulazione = "DOSBox"
    elif "scummvm.exe" in nomi_minuscoli:
        wrapper_emulazione = "ScummVM"

    return {
        "game_engine": engine,
        "metodo_rilevamento_engine": metodo_rilevamento,
        "ambiente_esecuzione": wrapper_emulazione
    }

def trova_eseguibile_reale(tutti_i_file: list, percorso_launcher: Path) -> Path:
    cartelle_da_escludere = {
        "redist", "__redist", "_commonredist", "directx", 
        "support", "docs", "manual", "extras", "bonus", "toolset"
    }
    parole_file_da_escludere = {
        "unins", "crash", "launcher", "setup", "config", 
        "redist", "vcredist", "dxsetup", "updater", "autorun",
        "physx", "directx", "dotnet", "oalinst", "xnafx", "toolset"
    }
    
    tutti_gli_exe = [f for f in tutti_i_file if f.suffix.lower() == ".exe"]
    if not tutti_gli_exe:
        return None

    candidati = []
    for f in tutti_gli_exe:
        parti_percorso = {parte.lower() for parte in f.parts}
        if parti_percorso.intersection(cartelle_da_escludere):
            continue
        nome_basso = f.name.lower()
        if not any(parola in nome_basso for parola in parole_file_da_escludere):
            candidati.append(f)
                
    if candidati:
        return max(candidati, key=lambda f: f.stat().st_size)
        
    if percorso_launcher and percorso_launcher.exists():
        return percorso_launcher

    non_uninstaller = [f for f in tutti_gli_exe if "unins" not in f.name.lower()]
    if non_uninstaller:
        return max(non_uninstaller, key=lambda f: f.stat().st_size)
        
    return tutti_gli_exe

def registra_report_ingest(db_path: Path, id_gioco: str, nome_manifest: str, hash_manifest: str, num_file: int, dim_mb: float, aggiornato: bool):
    """
    Registra automaticamente nel database il Condition Report iniziale (o di aggiornamento)
    collegato al manifest SHA-256 appena generato.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
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

    data_ora = datetime.now(timezone.utc).isoformat()
    tipo_op = "Baseline Manifest Updated (--forza)" if aggiornato else "Initial Ingest & Baseline Manifest"
    note = f"Generato manifest integrale '{nome_manifest}' tracciando {num_file} file ({dim_mb} MB)."

    cursore.execute("""
        INSERT INTO condition_reports (
            id_gioco, data_ispezione, tipo_operazione, agente,
            stato_integrita, manifest_riferimento, hash_rilevato, note_tecniche
        ) VALUES (?, ?, ?, 'Ingest Extractor v1.0', 'INTACT', ?, ?, ?);
    """, (id_gioco, data_ora, tipo_op, nome_manifest, hash_manifest, note))

    conn.commit()
    conn.close()
    aggiorna_file_condition_report(db_path, id_gioco)

def esegui_estrazione_modulo1(radice: Path, cartella_out: Path, percorso_config: Path):
    print(f"Avvio scansione di: {radice.name}...", flush=True)

    cartelle_escl, estensioni_escl = carica_esclusioni(BASE_DIR / "config" / "esclusioni_audit.json")
    tutti_i_file = [
        f for f in radice.rglob("*")
        if f.is_file() and not file_da_ignorare(f, radice, cartelle_escl, estensioni_escl)
    ]
    peso_totale_byte = sum(f.stat().st_size for f in tutti_i_file)
    conteggio_estensioni = Counter(f.suffix.lower() for f in tutti_i_file if f.suffix)

    info_gog = leggi_manifest_gog(radice)
    file_settings = BASE_DIR / "config" / "settings.json"
    dir_installers = None
    if file_settings.exists():
        with open(file_settings, "r", encoding="utf-8") as fs:
            cfg_s = json.load(fs)
            if cfg_s.get("gog_installers_path"):
                dir_installers = Path(cfg_s["gog_installers_path"])

    lista_installer = cerca_installer_offline(dir_installers, info_gog.get("titolo_ufficiale", ""), radice.name)

    percorso_launcher = None
    if info_gog.get("trovato") and info_gog.get("eseguibile_dichiarato"):
        percorso_launcher = radice / info_gog["eseguibile_dichiarato"]

    percorso_exe_reale = trova_eseguibile_reale(tutti_i_file, percorso_launcher)

    nome_exe_stampa = percorso_exe_reale.name if percorso_exe_reale else "Nessun eseguibile trovato"
    print(f"Analisi dell'eseguibile principale ({nome_exe_stampa}) in corso...", flush=True)
    dettagli_pe = ispeziona_header_pe(percorso_exe_reale)
    hash_exe = calcola_sha256(percorso_exe_reale) if (percorso_exe_reale and percorso_exe_reale.exists()) else None

    tecnologie = rileva_tecnologie(tutti_i_file, conteggio_estensioni, percorso_config)

    documento_finale = {
        "metadati_processo": {
            "modulo": "Modulo 1 - Estrazione Grezza",
            "data_estrazione_utc": datetime.now(timezone.utc).isoformat(),
            "nome_cartella_origine": radice.name
        },
        "identificazione_gog": info_gog,
        "statistiche_pacchetto": {
            "numero_totale_file": len(tutti_i_file),
            "dimensione_totale_byte": peso_totale_byte,
            "dimensione_totale_mb": round(peso_totale_byte / (1024 * 1024), 2),
            "distribuzione_formati": dict(conteggio_estensioni.most_common())
        },
        "analisi_eseguibile_principale": {
            "nome_file": percorso_exe_reale.name if percorso_exe_reale else None,
            "percorso_relativo": str(percorso_exe_reale.relative_to(radice)) if (percorso_exe_reale and percorso_exe_reale.exists()) else None,
            "dimensione_byte": percorso_exe_reale.stat().st_size if (percorso_exe_reale and percorso_exe_reale.exists()) else None,
            "sha256": hash_exe,
            "pe_header": dettagli_pe
        },
        "ambiente_tecnico": tecnologie,
        "installer_offline_sip": {
            "presente": len(lista_installer) > 0,
            "totale_file": len(lista_installer),
            "dimensione_totale_mb": round(sum(i["dimensione_byte"] for i in lista_installer) / (1024 * 1024), 2),
            "files": lista_installer
        }
    }

    cartella_out.mkdir(parents=True, exist_ok=True)
    nome_file_out = f"{radice.name.replace(' ', '_')}_modulo1.json"
    file_destinazione = cartella_out / nome_file_out

    with open(file_destinazione, "w", encoding="utf-8") as f:
        json.dump(documento_finale, f, indent=4, ensure_ascii=False)

    print(f"Completato! Salvato in: {file_destinazione.name}", flush=True)

    # Generazione del Manifest Integrale SHA-256 (immutabile dopo la prima acquisizione)
    nome_manifest_out = f"{radice.name.replace(' ', '_')}_manifest_sha256.json"
    file_manifest_dest = cartella_out / nome_manifest_out

    if file_manifest_dest.exists() and "--forza" not in sys.argv:
        print(f"Manifest integrale già presente ({file_manifest_dest.name}): baseline originale preservata.", flush=True)
    else:
        totale = len(tutti_i_file)
        print(f"PROGRESSO|0|Avvio calcolo SHA-256 per {radice.name} ({totale} file)...", flush=True)
        manifest_file = {}
        for idx, f in enumerate(tutti_i_file, start=1):
            if idx % 250 == 0 or idx == totale:
                perc = int((idx / totale) * 100)
                print(f"PROGRESSO|{perc}|{radice.name}: {idx}/{totale} file ({perc}%)", flush=True)
            percorso_rel_str = str(f.relative_to(radice)).replace("\\", "/")
            manifest_file[percorso_rel_str] = {
                "dimensione_byte": f.stat().st_size,
                "sha256": calcola_sha256(f)
            }

        documento_manifest = {
            "gog_game_id": f"GOG-{info_gog.get('gog_game_id')}",
            "titolo": info_gog.get("titolo_ufficiale"),
            "data_creazione_manifest_utc": datetime.now(timezone.utc).isoformat(),
            "totale_file_tracciati": len(manifest_file),
            "files": manifest_file
        }

        with open(file_manifest_dest, "w", encoding="utf-8") as fm:
            json.dump(documento_manifest, fm, indent=2, ensure_ascii=False)

        hash_del_manifest = calcola_sha256(file_manifest_dest)
        id_gioco_completo = f"GOG-{info_gog.get('gog_game_id')}"
        è_aggiornamento = "--forza" in sys.argv

        registra_report_ingest(
            BASE_DIR / "database" / "archivio_giochi.db",
            id_gioco_completo,
            nome_manifest_out,
            hash_del_manifest,
            len(manifest_file),
            round(peso_totale_byte / (1024 * 1024), 2),
            è_aggiornamento
        )

        print(f"Manifest integrale salvato e registrato nel Condition Report: {file_manifest_dest.name}", flush=True)

if __name__ == "__main__":
    FILE_SETTINGS = BASE_DIR / "config" / "settings.json"
    FILE_FIRME = BASE_DIR / "config" / "firme_engine.json"
    CARTELLA_OUTPUT = BASE_DIR / "output_json"

    if not FILE_SETTINGS.exists():
        print("ERRORE: Crea 'config/settings.json' partendo da 'config/settings.example.json'.")
        exit(1)

    with open(FILE_SETTINGS, "r", encoding="utf-8") as f:
        settings = json.load(f)

    cartella_libreria = Path(settings.get("gog_library_path", ""))
    if not cartella_libreria.exists():
        print(f"ERRORE: Il percorso libreria GOG '{cartella_libreria}' non esiste.")
        exit(1)

    for sottocartella in cartella_libreria.iterdir():
        if sottocartella.is_dir():
            if not list(sottocartella.glob("goggame-*.info")):
                print(f"[SALTATO] {sottocartella.name}: gioco non installato.")
                continue
            esegui_estrazione_modulo1(sottocartella, CARTELLA_OUTPUT, FILE_FIRME)
            print("-" * 50)
