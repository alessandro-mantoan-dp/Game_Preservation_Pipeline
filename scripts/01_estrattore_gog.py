import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import pefile

# Calcola dinamicamente la cartella radice del progetto (risale da scripts/ alla cartella principale)
BASE_DIR = Path(__file__).resolve().parent.parent

def calcola_sha256(percorso_file: Path) -> str:
    hasher = hashlib.sha256()
    with open(percorso_file, 'rb') as f:
        while blocco := f.read(65536):
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

def esegui_estrazione_modulo1(radice: Path, cartella_out: Path, percorso_config: Path):
    print(f"Avvio scansione di: {radice.name}...")

    tutti_i_file = [f for f in radice.rglob("*") if f.is_file()]
    peso_totale_byte = sum(f.stat().st_size for f in tutti_i_file)
    conteggio_estensioni = Counter(f.suffix.lower() for f in tutti_i_file if f.suffix)

    info_gog = leggi_manifest_gog(radice)

    percorso_launcher = None
    if info_gog.get("trovato") and info_gog.get("eseguibile_dichiarato"):
        percorso_launcher = radice / info_gog["eseguibile_dichiarato"]

    percorso_exe_reale = trova_eseguibile_reale(tutti_i_file, percorso_launcher)

    nome_exe_stampa = percorso_exe_reale.name if percorso_exe_reale else "Nessun eseguibile trovato"
    print(f"Analisi dell'eseguibile principale ({nome_exe_stampa}) in corso...")
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
        "ambiente_tecnico": tecnologie
    }

    cartella_out.mkdir(parents=True, exist_ok=True)
    nome_file_out = f"{radice.name.replace(' ', '_')}_modulo1.json"
    file_destinazione = cartella_out / nome_file_out

    with open(file_destinazione, "w", encoding="utf-8") as f:
        json.dump(documento_finale, f, indent=4, ensure_ascii=False)

    print(f"Completato! Salvato in: {file_destinazione.name}")

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
