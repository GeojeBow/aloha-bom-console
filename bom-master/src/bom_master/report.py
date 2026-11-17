"""Styled Excel report for corrective-action feedback."""
import datetime as dt
from collections import Counter, defaultdict

from openpyxl import Workbook
from openpyxl.formatting.rule import DataBarRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from . import VERSION
from .analyzer import FOLDER_COLS, ISSUE_TYPES, MASTER_COLS, ROLE_TITLE, ROLES, SEV_RANK, diff_rows, folder_fields
from .scanner import FIELD_IDS, FIELD_TITLE

NAVY = "14202E"
HEAD_FILL = PatternFill("solid", fgColor="1F2E40")
HEAD_FONT = Font(name="Segoe UI", bold=True, color="FFFFFF", size=10)
BODY = Font(name="Segoe UI", size=10)
BOLD = Font(name="Segoe UI", size=10, bold=True)
MUTED = Font(name="Segoe UI", size=9, color="66727F")
DELETED = Font(name="Segoe UI", size=10, color="B42318", strike=True)
TITLE = Font(name="Segoe UI", size=18, bold=True, color=NAVY)
H2 = Font(name="Segoe UI", size=12, bold=True, color=NAVY)
THIN = Side(style="thin", color="DDE2E8")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")
CENTER = Alignment(horizontal="center", vertical="center")

FILL = {
    "ERROR": ("FBE2E1", "B42318"), "WARN": ("FCF0D2", "8A5A00"), "INFO": ("E1ECFB", "1F5BB5"),
    "OK": ("DDF3E8", "1D7446"), "NONE": ("EDF0F3", "66727F"), "YELLOW": ("FFF3B0", "5C4A00"),
    "ACK": ("E4E8F0", "5B6B8C"),
}
STATUS_KIND = {
    "In sync": "OK", "Matches": "OK", "Not in WP": "WARN", "-": "NONE", "": "NONE",
    "WP outdated": "ERROR", "Content differs": "ERROR", "WP ahead": "ERROR", "WP only": "ERROR",
    "Differs": "ERROR", "Rev missing": "ERROR",
}


def _fill(kind):
    bg, fg = FILL[kind]
    return PatternFill("solid", fgColor=bg), Font(name="Segoe UI", size=10, bold=True, color=fg)


def _header(ws, row, titles, widths=None):
    for c, t in enumerate(titles, start=1):
        cell = ws.cell(row=row, column=c, value=t)
        cell.fill = HEAD_FILL
        cell.font = HEAD_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        cell.border = BOX
    ws.row_dimensions[row].height = 30
    if widths:
        for c, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(c)].width = w


def _paint(cell, kind):
    f, fo = _fill(kind)
    cell.fill = f
    cell.font = fo


def build_report(cfg, res, path, ships=None, progress=None):
    ships = ships or res.ships()
    keys = [k for k in res.keys.values() if k.ship in ships]
    issues = [i for i in res.issues if i.ship in ships and not i.ack]
    acked = [i for i in res.issues if i.ship in ships and i.ack]
    master = [r for r in res.master if r["_key"].split("-")[0] in ships]
    hull_txt = ", ".join(cfg.ship_label(s) for s in ships)
    wb = Workbook()

    # ------------------------------------------------------------ Summary
    ws = wb.active
    ws.title = "Summary"
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 3
    for col, w in zip("BCDEFGHI", (64, 14, 14, 14, 14, 14, 14, 14)):
        ws.column_dimensions[col].width = w
    ws["B2"] = "Electrical BOM Master — Consistency Report"
    ws["B2"].font = TITLE
    ws["B3"] = (f"Hull {hull_txt}   ·   Scanned {dt.datetime.fromtimestamp(res.scanned_at):%Y-%m-%d %H:%M}"
                f"   ·   BOM Master v{VERSION}")
    ws["B3"].font = MUTED
    ws["B4"] = f"Source: {cfg['base']}"
    ws["B4"].font = MUTED

    n_err = sum(1 for i in issues if i.sev == "ERROR")
    n_warn = sum(1 for i in issues if i.sev == "WARN")
    bad_boms = sum(1 for k in keys if k.worst == "ERROR")
    sync = sum(1 for k in keys if k.wp_status == "SYNC")
    with_prod = sum(1 for k in keys if k.prod)
    n_del = sum(1 for m in master if m.get("_deleted"))
    kpis = [("BOMs", len(keys), None), (f"Active lines ({n_del:,} deleted)", len(master) - n_del, None),
            ("BOMs needing correction", bad_boms, "ERROR"), ("Errors", n_err, "ERROR"),
            (f"Warnings (+{len(acked)} acknowledged)", n_warn, "WARN"),
            ("WP in sync", f"{sync}/{with_prod}", "OK")]
    r = 6
    for c, (lab, val, kind) in enumerate(kpis, start=2):
        top = ws.cell(row=r, column=c, value=val)
        top.font = Font(name="Segoe UI", size=18, bold=True, color=FILL[kind][1] if kind else NAVY)
        top.alignment = CENTER
        lab_c = ws.cell(row=r + 1, column=c, value=lab)
        lab_c.font = MUTED
        lab_c.alignment = Alignment(horizontal="center", wrap_text=True)
        for rr in (r, r + 1):
            ws.cell(row=rr, column=c).border = BOX
    ws.row_dimensions[r].height = 34
    ws.row_dimensions[r + 1].height = 30

    r = 10
    ws.cell(row=r, column=2, value="Four source folders").font = H2
    r += 1
    _header(ws, r, ["", "Folder", "BOMs OK", "Check", "Need correction", "No file", "Issues"])
    ws.cell(row=r, column=1).fill = PatternFill()
    for role in ROLES:
        r += 1
        kinds = Counter(k.folder(role)[1] for k in keys)
        n_iss = sum(1 for i in issues if role in i.roles)
        vals = [ROLE_TITLE[role], kinds["OK"], kinds["WARN"], kinds["ERROR"], kinds["NONE"], n_iss]
        for c, v in enumerate(vals, start=2):
            cell = ws.cell(row=r, column=c, value=v)
            cell.font = BOLD if c == 2 else BODY
            cell.border = BOX
        for c, kind in ((3, "OK"), (4, "WARN"), (5, "ERROR")):
            if ws.cell(row=r, column=c).value:
                _paint(ws.cell(row=r, column=c), kind)

    r += 2
    ws.cell(row=r, column=2, value="Issues by type").font = H2
    r += 1
    _header(ws, r, ["", "Issue", "Severity", "Count", "BOMs"])
    ws.cell(row=r, column=1).fill = PatternFill()
    by_code = Counter(i.code for i in issues)
    boms_by_code = defaultdict(set)
    for i in issues:
        boms_by_code[i.code].add(i.key)
    first = r + 1
    for code, n in sorted(by_code.items(), key=lambda kv: (-SEV_RANK[ISSUE_TYPES[kv[0]][0]], -kv[1])):
        r += 1
        sev, title, _ = ISSUE_TYPES[code]
        ws.cell(row=r, column=2, value=title).font = BODY
        _paint(ws.cell(row=r, column=3, value=sev), sev)
        ws.cell(row=r, column=4, value=n).font = BODY
        ws.cell(row=r, column=5, value=len(boms_by_code[code])).font = BODY
        for c in range(2, 6):
            ws.cell(row=r, column=c).border = BOX
    if r >= first:
        ws.conditional_formatting.add(f"D{first}:D{r}", DataBarRule(start_type="num", start_value=0, end_type="max",
                                                                     color="E07A72", showValue=True))

    r += 2
    ws.cell(row=r, column=2, value="Status by block group").font = H2
    r += 1
    _header(ws, r, ["", "Hull / Group", "BOMs", "OK", "Warning", "Error", "WP in sync", "WP issue", "Has DCN/ECN"])
    ws.cell(row=r, column=1).fill = PatternFill()
    grp = defaultdict(list)
    for k in keys:
        grp[(k.ship, k.group)].append(k)
    for (ship, g), kl in sorted(grp.items()):
        r += 1
        vals = [f"{cfg.ship_label(ship)}  {g}-blocks", len(kl),
                sum(1 for k in kl if k.worst is None or k.worst == "INFO"),
                sum(1 for k in kl if k.worst == "WARN"), sum(1 for k in kl if k.worst == "ERROR"),
                sum(1 for k in kl if k.wp_status == "SYNC"),
                sum(1 for k in kl if k.wp_status in ("OUTDATED", "MISMATCH", "AHEAD", "WP_ONLY", "MISSING")),
                sum(1 for k in kl if k.cn_files)]
        for c, v in enumerate(vals, start=2):
            cell = ws.cell(row=r, column=c, value=v)
            cell.font = BODY
            cell.border = BOX
        for c, kind in ((4, "OK"), (5, "WARN"), (6, "ERROR")):
            if ws.cell(row=r, column=c).value:
                _paint(ws.cell(row=r, column=c), kind)

    r += 2
    ws.cell(row=r, column=2, value="How to read this report").font = H2
    notes = [
        "Action List — one row per problem, worst first. Fill in Owner / Status / Due to track correction.",
        "Sync Matrix — every BOM with its latest Prod DWG revision against Work Package and DCN/ECN copies.",
        "Content Diffs — line-by-line differences behind every 'different content' issue (yellow = changed cell).",
        "Master BOM — all lines of the latest Prod DWG BOM per hull with status columns.",
        "Rule: 16 Prod DWG is the reference (100%). Work Package must hold the same latest revision with identical "
        "content. DCN/ECN BOMs are optional, but any that exist must match Prod DWG and Work Package.",
        "Content comparison uses the 20 standard SAP columns; free-text note columns (REMARK etc.) are ignored.",
    ]
    for n in notes:
        r += 1
        ws.cell(row=r, column=2, value=n).font = BODY
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=9)
        ws.cell(row=r, column=2).alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[r].height = 30

    if progress:
        progress("Action list")
    # ------------------------------------------------------------ Action list
    ws = wb.create_sheet("Action List")
    cols = ["#", "Severity", "Hull", "BOM", "Rev", "Folder", "Issue", "Detail", "Corrective action", "File(s)",
            "Owner", "Status", "Due", "Comment"]
    _header(ws, 1, cols, [5, 10, 8, 22, 10, 22, 36, 60, 46, 70, 14, 12, 12, 30])
    order = {r: n for n, r in enumerate(ROLES)}
    for n, i in enumerate(issues, start=1):
        rr = n + 1
        folders = " + ".join(ROLE_TITLE[r] for r in sorted(i.roles, key=order.get))
        vals = [n, i.sev, cfg.ship_label(i.ship), i.key, i.rev, folders, i.title, i.detail, i.action,
                "\n".join(f.path for f in i.files[:4]), "", "Open", "", ""]
        for c, v in enumerate(vals, start=1):
            cell = ws.cell(row=rr, column=c, value=v)
            cell.font = BODY
            cell.alignment = WRAP
            cell.border = BOX
        _paint(ws.cell(row=rr, column=2), i.sev)
        ws.cell(row=rr, column=4).font = BOLD
    ws.freeze_panes = "E2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{max(2, len(issues) + 1)}"

    # ------------------------------------------------------------ Acknowledged minor alarms
    ws = wb.create_sheet("Acknowledged (minor)")
    cols = ["Severity", "Hull", "BOM", "Rev", "Issue", "Detail", "Acknowledged by", "When", "Reason"]
    _header(ws, 1, cols, [10, 8, 22, 10, 36, 60, 16, 17, 60])
    for n, i in enumerate(acked, start=2):
        a = i.ack
        vals = [i.sev, cfg.ship_label(i.ship), i.key, i.rev, i.title, i.detail, a.get("by", ""), a.get("at", ""),
                a.get("note", "")]
        for c, v in enumerate(vals, start=1):
            cell = ws.cell(row=n, column=c, value=v)
            cell.font = MUTED if c != 9 else BODY
            cell.alignment = WRAP
            cell.border = BOX
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = f"A1:I{max(2, len(acked) + 1)}"

    if progress:
        progress("Sync matrix")
    # ------------------------------------------------------------ Sync matrix
    ws = wb.create_sheet("Sync Matrix")
    cols = ["Hull", "Group", "BOM"] + [t for _, t in FOLDER_COLS] + [
        "Overall", "Lines", "Errors", "Warnings", "Prod DWG file", "Work Package file", "DCN / ECN files"]
    _header(ws, 1, cols, [8, 7, 22, 20, 20, 16, 16, 22, 8, 8, 9, 70, 70, 70])
    for n, k in enumerate(sorted(keys, key=lambda k: k.key), start=2):
        ff = folder_fields(k)
        vals = [cfg.ship_label(k.ship), k.group, k.key] + [ff[c] for c, _ in FOLDER_COLS] + [
            ff["overall"], len(k.prod.rows) if k.prod else 0,
            sum(1 for i in k.issues if i.sev == "ERROR"), sum(1 for i in k.issues if i.sev == "WARN"),
            k.prod.path if k.prod else "", k.wp.path if k.wp else "",
            "\n".join(f.path for f in k.cn_files)]
        for c, v in enumerate(vals, start=1):
            cell = ws.cell(row=n, column=c, value=v)
            cell.font = BODY
            cell.border = BOX
        ws.cell(row=n, column=3).font = BOLD
        for c, (fld, _) in enumerate(FOLDER_COLS + [("overall", "")], start=4):
            _paint(ws.cell(row=n, column=c), ff["_kind:" + fld])
        if vals[10]:
            _paint(ws.cell(row=n, column=10), "ERROR")
        if vals[11]:
            _paint(ws.cell(row=n, column=11), "WARN")
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{len(keys) + 1}"

    if progress:
        progress("Content diffs")
    # ------------------------------------------------------------ Content diffs
    ws = wb.create_sheet("Content Diffs")
    cols = ["BOM", "Rev", "File A", "File B", "Change", "Material No."] + [FIELD_TITLE[f] for f in FIELD_IDS]
    _header(ws, 1, cols, [22, 8, 46, 46, 12, 22] + [14] * len(FIELD_IDS))
    rr = 1
    yellow, yfont = _fill("YELLOW")
    for i in issues:
        if i.code not in ("SAME_NAME_DIFF", "WP_CONTENT_DIFF", "CN_CONTENT_DIFF", "SAME_REV_DIFF") or len(i.files) < 2:
            continue
        a = i.files[0]
        for b in i.files[1:]:
            for kind, key, ra, rb, ch in diff_rows(a.rows, b.rows):
                ch = [f for f in ch if not f.startswith("x:")]
                if kind == "CHANGED" and not ch:
                    continue
                rr += 1
                label = {"CHANGED": "Changed", "ONLY_A": "Only in A", "ONLY_B": "Only in B"}[kind]
                head = [i.key, i.rev, f"{a.role}\\{a.rel}", f"{b.role}\\{b.rel}", label, key]
                for c, v in enumerate(head, start=1):
                    cell = ws.cell(row=rr, column=c, value=v)
                    cell.font = BODY
                    cell.border = BOX
                _paint(ws.cell(row=rr, column=5),
                       {"CHANGED": "WARN", "ONLY_A": "ERROR", "ONLY_B": "OK"}[kind])
                for c, f in enumerate(FIELD_IDS, start=7):
                    va, vb = (ra or {}).get(f, ""), (rb or {}).get(f, "")
                    if kind == "CHANGED" and f in ch:
                        cell = ws.cell(row=rr, column=c, value=f"{va} → {vb}")
                        cell.fill = yellow
                        cell.font = yfont
                    else:
                        cell = ws.cell(row=rr, column=c, value=va if ra else vb)
                        cell.font = BODY
                    cell.border = BOX
                if rr > 60000:
                    break
    ws.freeze_panes = "G2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{max(rr, 2)}"

    # ------------------------------------------------------------ Master BOM per hull
    sev_kind = {"ERROR": "ERROR", "WARN": "WARN"}
    for ship in ships:
        if progress:
            progress(f"Master BOM {cfg.ship_label(ship)}")
        rows = [m for m in master if m["_key"].startswith(ship + "-")]
        if not rows:
            continue
        ws = wb.create_sheet(f"Master BOM {cfg.ship_label(ship)}")
        titles = [t for _, t in MASTER_COLS]
        widths = [7, 22, 22, 12, 34, 20, 20, 16, 16, 22, 12, 15, 11] + [14] * (len(FIELD_IDS) - 2) + [26, 60]
        _header(ws, 1, titles, widths)
        chip_cols = [(i, c) for i, (c, _) in enumerate(MASTER_COLS, start=1)
                     if "_kind:" + c in (rows[0] if rows else {})]
        for n, m in enumerate(rows, start=2):
            for c, (f, _) in enumerate(MASTER_COLS, start=1):
                cell = ws.cell(row=n, column=c, value=m.get(f, ""))
                if m.get("_deleted"):
                    cell.font = DELETED
            for c, fld in chip_cols:
                kind = m["_kind:" + fld]
                if kind != "NONE":
                    _paint(ws.cell(row=n, column=c), kind)
        ws.freeze_panes = "C2"
        ws.auto_filter.ref = f"A1:{get_column_letter(len(MASTER_COLS))}{len(rows) + 1}"

    # ------------------------------------------------------------ File inventory
    if progress:
        progress("File inventory")
    ws = wb.create_sheet("File Inventory")
    cols = ["Source", "Location", "Hull", "BOM", "Rev", "File name", "Lines", "Modified", "Read error", "Path"]
    _header(ws, 1, cols, [8, 11, 8, 22, 6, 40, 7, 17, 30, 90])
    files = [f for f in res.files if f.ship in ships]
    for n, f in enumerate(files, start=2):
        vals = [f.role, f.loc, cfg.ship_label(f.ship), f.key, f.rev, f.name, len(f.rows),
                dt.datetime.fromtimestamp(f.mtime).strftime("%Y-%m-%d %H:%M"), f.error, f.path]
        for c, v in enumerate(vals, start=1):
            ws.cell(row=n, column=c, value=v)
        loc_kind = {"ACTIVE": "OK", "ARCHIVE": "NONE", "COMMENT": "INFO", "STAGING": "WARN"}[f.loc]
        _paint(ws.cell(row=n, column=2), loc_kind)
        if f.error:
            _paint(ws.cell(row=n, column=9), "ERROR")
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = f"A1:J{len(files) + 1}"

    if progress:
        progress("Saving workbook")
    wb.save(path)
    return path


# ---------------------------------------------------------------- 전장설계 Master BOM check
def build_master_check_report(cfg, chk, path, ships=None, progress=None):
    """Excel feedback for whoever maintains the 전장설계 Master BOM: every place it differs from the folders."""
    from .master_check import DIFF_COLS, KINDS, diff_row
    ships = ships or sorted({k.ship for k in chk.keys.values()})
    keys = sorted((k for k in chk.keys.values() if k.ship in ships), key=lambda k: k.key)
    diffs = [(d, k) for k in keys for d in k.diffs]
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 3
    ws.column_dimensions["B"].width = 58
    for col in "CDE":
        ws.column_dimensions[col].width = 16
    ws["B2"] = "전장설계 Master BOM Check — Master BOM vs. folders"
    ws["B2"].font = TITLE
    ws["B3"] = (f"Master file: {chk.path}   ·   Hulls: {', '.join(cfg.ship_label(s) for s in ships)}   ·   "
                f"Checked {dt.datetime.fromtimestamp(chk.checked_at):%Y-%m-%d %H:%M}   ·   BOM Master v{VERSION}")
    ws["B3"].font = MUTED
    ws["B4"] = ("Reference = latest BOM in 16 Prod DWG (S041/S042 without own Prod DWG BOMs: S040 Prod DWG). "
                "The Master BOM must be identical. / 기준 = 16 Prod DWG 최신 BOM. Master BOM은 이와 같아야 함.")
    ws["B4"].font = MUTED
    st = Counter(k.status for k in keys)
    r = 6
    _header(ws, r, ["", "BOM status / BOM 상태", "BOMs"])
    for lab, kind in (("Matches", "OK"), ("Differs", "ERROR"), ("Missing in Master", "ERROR"),
                      ("Not in folders", "ERROR")):
        r += 1
        ws.cell(row=r, column=2, value=lab).font = BODY
        c = ws.cell(row=r, column=3, value=st[lab])
        _paint(c, kind if st[lab] else "NONE")
    r += 2
    _header(ws, r, ["", "Difference / 차이", "Count / 건수", "BOMs"])
    cnt = Counter(d.kind for d, _ in diffs)
    boms = defaultdict(set)
    for d, k in diffs:
        boms[d.kind].add(k.key)
    for kind, (sev, en, ko, _a) in KINDS.items():
        r += 1
        ws.cell(row=r, column=2, value=f"{en} / {ko}").font = BODY
        c = ws.cell(row=r, column=3, value=cnt[kind])
        _paint(c, sev if cnt[kind] else "NONE")
        ws.cell(row=r, column=4, value=len(boms[kind])).font = BODY
    if chk.warnings:
        r += 2
        ws.cell(row=r, column=2, value="Notes on reading the Master file").font = H2
        for w in chk.warnings:
            r += 1
            ws.cell(row=r, column=2, value=w).font = MUTED

    if progress:
        progress("BOM status")
    ws = wb.create_sheet("BOM status")
    cols = ["Hull", "BOM", "Status / 상태", "Prod DWG rev", "Master rev", "Prod DWG lines", "Master lines",
            "Missing lines", "Extra lines", "Value diffs", "Basis / 기준"]
    _header(ws, 1, cols, [8, 22, 18, 12, 12, 13, 13, 12, 12, 12, 22])
    for i, k in enumerate(keys, start=2):
        kc = Counter(d.kind for d in k.diffs)
        vals = [cfg.ship_label(k.ship), k.key, k.status,
                f"R{k.folder_rev}" if k.folder_rev is not None else "",
                "/".join(f"R{x}" for x in k.master_revs), k.folder_lines if k.in_folder else "",
                k.master_lines or "", kc["LINE_MISSING"] or "", kc["LINE_EXTRA"] or "", kc["VALUE_DIFF"] or "",
                k.basis]
        for c, v in enumerate(vals, start=1):
            cell = ws.cell(row=i, column=c, value=v)
            cell.font = BODY
            cell.border = BOX
        _paint(ws.cell(row=i, column=3), "OK" if k.status == "Matches" else "ERROR")
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = ws.dimensions

    if progress:
        progress("Differences")
    ws = wb.create_sheet("Differences")
    _header(ws, 1, [t for _, t in DIFF_COLS], [9, 8, 22, 30, 18, 8, 34, 18, 22, 22, 18, 16, 50])
    i = 1
    for d, k in diffs:
        if d.kind == "DELETED_OMITTED":
            continue
        i += 1
        row = diff_row(d, cfg, k)
        for c, (f, _t) in enumerate(DIFF_COLS, start=1):
            cell = ws.cell(row=i, column=c, value=row[f])
            cell.font = BODY
            cell.border = BOX
            if f == "action":
                cell.alignment = WRAP
        _paint(ws.cell(row=i, column=1), row["sev"])
        if d.kind == "VALUE_DIFF":
            _paint(ws.cell(row=i, column=10), "YELLOW")
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = ws.dimensions
    wb.save(path)
    return path
