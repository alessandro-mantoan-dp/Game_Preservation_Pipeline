import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

def aggiorna_file_condition_report(db_path: Path, id_gioco: str):
    """
    Legge dal database tutti i Condition Report di un gioco e genera/aggiorna
    il relativo registro storico leggibile in formato Markdown in output_reports/.
    """
    if not db_path.exists():
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursore = conn.cursor()

    cursore.execute("SELECT titolo FROM giochi WHERE id_gioco = ?;", (id_gioco,))
    riga_gioco = cursore.fetchone()
    titolo = riga_gioco["titolo"] if riga_gioco else id_gioco

    cursore.execute("""
        SELECT id_report, data_ispezione, tipo_operazione, agente,
               stato_integrita, manifest_riferimento, hash_rilevato, note_tecniche
        FROM condition_reports
        WHERE id_gioco = ?
        ORDER BY data_ispezione DESC;
    """, (id_gioco,))
    reports = [dict(r) for r in cursore.fetchall()]
    conn.close()

    if not reports:
        return

    cartella_out = BASE_DIR / "output_reports"
    cartella_out.mkdir(parents=True, exist_ok=True)

    nome_pulito = "".join(c if c.isalnum() or c in (" ", "_", "-") else "_" for c in titolo).strip().replace(" ", "_")
    file_md = cartella_out / f"{nome_pulito}_condition_report.md"

    stato_attuale = reports[0]["stato_integrita"]
    ultima_data = reports[0]["data_ispezione"][:19].replace("T", " ")

    righe = [
        f"# Condition Report: {titolo}",
        "",
        f"- **Identificativo Archivio:** `{id_gioco}`",
        f"- **Stato di Conservazione Attuale:** **{stato_attuale}**",
        f"- **Ultimo Controllo Registrato:** {ultima_data} UTC",
        f"- **Totale Ispezioni / Operazioni:** {len(reports)}",
        "",
        "---",
        "",
        "## Cronologia degli Eventi e delle Ispezioni",
        ""
    ]

    for rep in reports:
        data_ev = rep["data_ispezione"][:19].replace("T", " ")
        righe.append(f"### [{rep['stato_integrita']}] {rep['tipo_operazione']} — {data_ev} UTC")
        righe.append(f"- **Agente:** {rep['agente']}")
        if rep.get("manifest_riferimento"):
            righe.append(f"- **Manifest di riferimento:** `{rep['manifest_riferimento']}`")
        if rep.get("hash_rilevato"):
            righe.append(f"- **Hash SHA-256 rilevato:** `{rep['hash_rilevato']}`")
        righe.append(f"- **Note tecniche:** {rep['note_tecniche']}")
        righe.append("")

    file_md.write_text("\n".join(righe), encoding="utf-8")

def rigenera_tutti_i_reports(db_path: Path):
    """
    Esporta o aggiorna i file Markdown per tutti i giochi presenti nel database.
    """
    if not db_path.exists():
        return
    conn = sqlite3.connect(db_path)
    cursore = conn.cursor()
    cursore.execute("SELECT DISTINCT id_gioco FROM condition_reports;")
    ids = [r[0] for r in cursore.fetchall()]
    conn.close()

    for id_g in ids:
        aggiorna_file_condition_report(db_path, id_g)
