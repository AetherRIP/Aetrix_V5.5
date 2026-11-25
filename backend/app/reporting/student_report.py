"""The single-student correction PDF, extracted from Math Checker V5.

Source: GitHub ``AetherRIP/MATH_CHECKER_V5`` at commit
``fe27e4220f42f14d4f6ad684e118b999901bc765``, file
``backend/app/api/report_routes.py``.  ``render_result_pdf`` and the three
private helpers it calls (``_subquestion_detail``, ``_question_block``,
``_finish_pdf``) are the V5 implementation unchanged apart from the interface
adaptations listed below; the layout, typography, wording, statistics and
question breakdown are V5's own.  The design system they compose lives beside
this module in :mod:`app.reporting.design`.

Adaptations, and nothing else:

* the assignment title arrives on the ``result`` mapping (``assignment_title``)
  instead of a ``coursework`` table read, so this module never touches a
  database;
* ``partial_summary`` comes from :mod:`app.reporting.verification` (V5's own
  function, copied out of its engine package);
* ``_count`` comes from :mod:`app.reporting.text` (V5's helper, copied
  verbatim);
* ``eyebrow`` and ``doc_prefix`` are parameters so the document carries
  Aetrix's product name while every visual rule stays V5's.

Aetrix data reaches this generator through :mod:`app.services.student_report`;
nothing here knows about tenants, jobs, approvals or Google Classroom.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime

from .text import count as _count


def _fmt_ts(ts) -> str:
    if not ts:
        return "—"
    try:
        return datetime.fromtimestamp(float(ts), tz=UTC).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OverflowError):
        return str(ts)


def render_result_pdf(result: dict, *, detail: str = "standard",
                      generated_at: float | None = None,
                      eyebrow: str = "Math Correct",
                      doc_prefix: str = "MC-") -> io.BytesIO:
    """Single-correction PDF: "how did THIS student do on THIS assignment?".

    Built entirely from the shared design system, so it shares one identity
    with every other Math Correct export. Information is reorganised into a
    hierarchy, not removed:

    page 1  who + how they did (score, percentage, performance verdict)
            -> performance summary -> question breakdown table
    later   one expandable-style block per question, with the student's work,
            the mark scheme, the awarded mark points and the correction

    The canonical display name and the teacher's class come from the caller
    (``student_identity.decorate``); this function never looks a name up
    itself, so the PDF can never disagree with the page the teacher was
    looking at.
    """
    from ..reporting import design as D

    inner = result.get("result_json") or {}
    questions = inner.get("questions") or []
    verification = result.get("verification_json") or {}
    notes = inner.get("overall_notes") or {}
    detail = (detail or "standard").lower()

    # V5 read the title from its own ``coursework`` table.  Aetrix passes the
    # title it already resolved, so the generator opens no database connection.
    assignment = result.get("assignment_title")

    def _mark(q: dict) -> tuple:
        maximum = q.get("max_marks") or 0
        awarded = q.get("awarded_marks") or 0
        return awarded, maximum

    full = sum(1 for q in questions
               if _mark(q)[0] == _mark(q)[1] and _mark(q)[1])
    zero = sum(1 for q in questions if _mark(q)[0] == 0)
    partial = len(questions) - full - zero
    review = sum(1 for q in questions if q.get("status") == "REVIEW")
    lost = sum(max(0, (q.get("max_marks") or 0) - (q.get("awarded_marks") or 0))
               for q in questions)

    from .verification import partial_summary
    partial_info = partial_summary(verification)

    student = str(result.get("display_name")
                  or result.get("student_name") or D.esc("Student"))
    class_label = str(result.get("class_label") or "Not assigned")

    brand = D.load_branding()
    theme = D.make_theme(accent=brand.accent or None, label="correction")
    styles = D.build_styles(theme)
    story: list = []

    # ---- headline: the number a teacher looks for first --------------------
    earned = result.get("earned")
    available = result.get("available")
    percentage = result.get("percentage")
    # A partial correction must never print a percentage that reads as a score
    # for the paper: the marked subset's fraction is not the student's result.
    D.add(story, D.stat_strip(theme, styles, [
        ("Marked only" if partial_info else "Score",
         D.fmt_score(earned, available)),
        ("Percentage", "—" if partial_info else D.fmt_pct(percentage)),
        ("Questions", str(len(questions)) if questions else "0"),
        ("Marks lost", D.fmt_num(lost)),
    ], tone="accent", bar_for=1))

    if partial_info:
        D.add(story, D.Spacer(1, 4))
        D.add(story, D.callout(theme, styles, "Incomplete correction", [
            f"Only {partial_info['marked_questions']} of "
            f"{partial_info['expected_questions']} questions have a mark "
            f"({partial_info['unresolved_questions']} are unmarked).",
            f"{partial_info['unresolved_marks']} of "
            f"{partial_info['paper_marks'] or '?'} marks were never assessed, "
            "so this is a DRAFT for review — not a result and not a grade.",
        ], tone="warn"))

    verdict = ("Incomplete" if partial_info
               else D.performance_word(percentage))
    verdict_tone = ("warn" if partial_info else
                    "ok" if percentage is not None and percentage >= 80
                    else "warn" if percentage is not None and percentage >= 50
                    else "mute")
    status = "Approved by teacher" if result.get("manual_override") else (
        "Needs review" if verification.get("status") == "REVIEW" else "Verified")
    status_tone = ("ok" if status == "Verified"
                   else "warn" if status == "Needs review" else "info")

    D.add(story, D.Spacer(1, 5))
    D.add(story, D.badges([(verdict, verdict_tone), (status, status_tone)],
                          theme))

    # ---- who and what -----------------------------------------------------
    D.add(story, D.Spacer(1, 5))
    D.add(story, D.section(theme, styles, "Student",
                           subtitle="Who this report is about"))
    meta = [
        ("Student", student),
        ("Class", class_label),
        ("Assignment", assignment or "Not recorded"),
        ("Date", D.esc(_fmt_ts(result.get("created_at")))),
        # NOTE: the AI model/provider that marked this work is deliberately NOT
        # printed. This PDF is student-facing, so it must never reveal which
        # model corrected the homework (§ report privacy). ``marking_model``
        # stays available in the database and the internal diagnostics/logs for
        # debugging and provider management - it is simply kept out of the
        # report the student receives.
    ]
    if result.get("classroom_name") and result.get("nickname"):
        # The teacher asked for the nickname; the official name stays visible
        # so the report can always be reconciled with Classroom.
        meta.append(("Classroom name", str(result["classroom_name"])))
    D.add(story, D.key_values(theme, styles, meta))

    if verification.get("anomalies"):
        D.add(story, D.Spacer(1, 4))
        D.add(story, D.callout(
            theme, styles, "This correction needs a second look",
            [str(a) for a in verification["anomalies"]], tone="warn",
            note="Verification flagged this result. Check it before the grade "
                 "is returned."))

    # ---- high-score double-check (§8/§19): never present the first result
    # as the final one. The row's earned/available/percentage ARE the final
    # result; the first/second raw corrections are reported separately.
    if result.get("double_check_triggered"):
        first = result.get("first_earned")
        first_max = result.get("first_available")
        second = result.get("second_earned")
        second_max = result.get("second_available")
        status = str(result.get("double_check_status") or "")
        review = bool(result.get("review_required"))
        tone = "warn" if (review or status == "REVIEW_REQUIRED") else (
            "ok" if status == "COMPLETE" else "warn")
        headline = {
            "COMPLETE": "Independently double-checked",
            "REVIEW_REQUIRED": "Double-check: REVIEW REQUIRED",
            "DOUBLE_CHECK_FAILED": "Double-check failed — first result kept",
        }.get(status, "Independently double-checked")
        rows = [("Status", headline)]
        if first is not None:
            rows.append(("First correction",
                         f"{D.fmt_score(first, first_max)} "
                         f"({D.fmt_pct(result.get('first_percentage'))})"))
        if second is not None:
            rows.append(("Second correction (independent)",
                         f"{D.fmt_score(second, second_max)} "
                         f"({D.fmt_pct(result.get('second_percentage'))})"))
        rows.append(("Final result",
                     f"{D.fmt_score(earned, available)} "
                     f"({D.fmt_pct(percentage)})"))
        if first is not None and second is not None:
            try:
                diff = int(first) - int(second)
                rows.append(("Difference", _count(diff, "mark")))
            except (TypeError, ValueError):
                pass
        if result.get("disagreement_status"):
            rows.append(("Agreement", str(result["disagreement_status"]).replace("_", " ").title()))
        reason = str(result.get("double_check_reason") or "")
        D.add(story, D.Spacer(1, 5))
        D.add(story, D.section(theme, styles, "Independent double-check",
                               subtitle="A second independent correction verified this score"))
        D.add(story, D.key_values(theme, styles, rows))
        diffs = result.get("double_check_question_differences") or []
        if diffs:
            bullets = [
                f"Question {d.get('question_number')}: first "
                f"{d.get('first_awarded')}/{d.get('max_marks')}, second "
                f"{d.get('second_awarded')}/{d.get('max_marks')}"
                + (f" — {d.get('second_loss_reason')}" if d.get("second_loss_reason") else "")
                for d in diffs[:12]
            ]
            D.add(story, D.Spacer(1, 3))
            D.add(story, D.callout(
                theme, styles, "Where the two corrections differed", bullets,
                tone="info",
                note="Only differences recorded by the corrections themselves "
                     "are listed."))
        if reason:
            D.add(story, D.Spacer(1, 3))
            D.add(story, D.callout(theme, styles, "Why", [reason], tone=tone))

    if notes.get("summary") or notes.get("strengths") or notes.get("revision_areas"):
        D.add(story, D.Spacer(1, 5))
        D.add(story, D.section(theme, styles, "Overview"))
        if notes.get("summary"):
            D.add(story, D.Paragraph(D.esc(notes["summary"]), styles["body"]))
            D.add(story, D.Spacer(1, 2))
        for label, key, _tone in (("Strengths", "strengths", "ok"),
                                  ("What to revise", "revision_areas", "warn")):
            values = notes.get(key) or []
            if not values:
                continue
            D.add(story, D.subsection(theme, styles, label))
            D.add(story, D.bullets(theme, styles, [str(v) for v in values]))

    if detail == "summary":
        return _finish_pdf(theme, brand, student, assignment, story,
                           generated_at, result, eyebrow=eyebrow,
                           doc_prefix=doc_prefix)

    # ---- question breakdown ----------------------------------------------
    D.add(story, D.Spacer(1, 5))
    D.add(story, D.section(
        theme, styles, "Question breakdown",
        subtitle=("Score and outcome for every question. Detailed marking "
                  "follows.")))
    if not questions:
        D.add(story, D.note(theme, styles,
                            "No question-level results were stored for this "
                            "correction."))
    else:
        rows, tones = [], []
        for q in questions:
            awarded, maximum = _mark(q)
            if q.get("status") == "REVIEW":
                state = "Unmarked - review"
            elif maximum and awarded == maximum:
                state = "Correct"
            elif awarded == 0:
                state = "No marks"
            else:
                state = "Partial"
            rows.append([f"Q{D.esc(q.get('question_number', '?'))}",
                         f"{D.fmt_num(awarded)} / {D.fmt_num(maximum)}",
                         state,
                         D.esc(q.get("loss_reason") or
                               (q.get("correct_method") or
                                "No comment recorded"))])
            tones.append(D.status_tone(state))
        D.add(story, D.data_table(
            theme, styles,
            ["Question", "Score", "Status", "Comment"], rows,
            widths=D.fit_widths(theme, [16, 14, 18, 52]),
            aligns=["left", "right", "left", "left"], row_tones=tones,
            emphasis=[1]))
        # The four counts are computed from the same rows the table prints,
        # so the line can never disagree with the table above it.
        tally = (f"{full} fully correct, {partial} with partial credit, "
                 f"{zero} with no marks")
        if review:
            tally += f" ({review} held for review)"
        D.add(story, D.Spacer(1, 1.6))
        D.add(story, D.note(theme, styles,
                            f"{tally}. {D.fmt_num(lost)} "
                            f"{'mark' if lost == 1 else 'marks'} lost in total "
                            "across "
                            f"{_count(len(questions), 'question')}."))

    # ---- one block per question, with the full marking detail --------------
    if detail == "detailed" and questions:
        D.add(story, D.Spacer(1, 5))
        D.add(story, D.section(
            theme, styles, "Marking detail",
            subtitle="Student work, mark scheme, awarded marks and correction."))
        for q in questions:
            D.add(story, _question_block(theme, styles, q))

    return _finish_pdf(theme, brand, student, assignment, story,
                       generated_at, result, eyebrow=eyebrow,
                       doc_prefix=doc_prefix)


def _subquestion_detail(sub: dict) -> str:
    """One subquestion row: its own mark, then the scheme evidence it has.

    An UNMARKED part is named as such: printing 0 would claim the marker
    awarded nothing when in fact it returned no row for that part.
    """
    maximum = sub.get("max_marks")
    maximum_text = maximum if maximum is not None else "?"
    if str(sub.get("status") or "").upper() != "MARKED":
        return f"UNMARKED - no mark was returned for this part (of {maximum_text})"
    awarded = sub.get("awarded_marks")
    text = f"{awarded if awarded is not None else 0} / {maximum_text} marks"
    answers = [str(a).strip() for a in sub.get("answers") or [] if str(a).strip()]
    if answers:
        text += " - scheme: " + " or ".join(answers)
    codes = [str(c).strip() for c in sub.get("mark_codes") or [] if str(c).strip()]
    if codes:
        text += " - points: " + ", ".join(codes)
    return text


def _question_block(theme, styles, q: dict):
    """One question as a self-contained block, never split across pages."""
    from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table, TableStyle

    from ..reporting import design as D

    awarded = q.get("awarded_marks") or 0
    maximum = q.get("max_marks") or 0
    if q.get("status") == "REVIEW":
        state, tone = "Unmarked - review", "warn"
    elif maximum and awarded == maximum:
        state, tone = "Correct", "ok"
    elif awarded == 0:
        state, tone = "No marks", "err"
    else:
        state, tone = "Partial", "warn"

    head = D._left(Table(
        [[Paragraph(f"Q{D.esc(q.get('question_number', '?'))}", styles["h3"]),
          Paragraph(f"<b>{D.fmt_num(awarded)} / {D.fmt_num(maximum)}</b> "
                    f"marks", styles["cell"])]],
        colWidths=[theme.width * 0.5, theme.width * 0.5]))
    head.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))

    items = []
    if q.get("student_answer") or q.get("working_summary"):
        items.append(("Student work",
                      str(q.get("student_answer") or q.get("working_summary"))))
    if q.get("correct_method"):
        items.append(("Mark scheme", str(q["correct_method"])))
    # Each subquestion keeps its own mark in the report, so a parent total of
    # "2 / 5" can be read down to the part that lost the marks.
    for sub in q.get("subquestions") or []:
        label = str(sub.get("label") or sub.get("id") or "?")
        items.append((f"Subquestion {label}", _subquestion_detail(sub)))
    for item in q.get("mark_breakdown") or []:
        mark = "awarded" if item.get("awarded") else "not awarded"
        items.append((f"Mark point {D.esc(item.get('code', ''))}",
                      f"{mark} - {item.get('reason', '')}".strip(" -")))
    if q.get("loss_reason"):
        items.append(("Where marks were lost", str(q["loss_reason"])))
    if q.get("full_mark_solution"):
        items.append(("Full-mark solution", str(q["full_mark_solution"])))

    block = [head, D.badges([(state, tone)], theme), Spacer(1, 2.2 * D.mm)]
    if items:
        block.append(D.key_values(theme, styles, items, columns=1))
    else:
        block.append(D.note(theme, styles,
                            "No mark-scheme detail was stored for this "
                            "question."))
    block.append(Spacer(1, 3.4 * D.mm))
    # KeepTogether so a question's heading is never stranded at a page foot.
    return KeepTogether(block)


def _finish_pdf(theme, brand, student, assignment, story, generated_at, result,
                *, eyebrow: str = "Math Correct", doc_prefix: str = "MC-"):
    """Hand the story to the design system and return the finished buffer."""
    from datetime import datetime

    from ..reporting import design as D

    context_bits = [b for b in (student, assignment) if b]
    report = D.Report(
        theme=theme, branding=brand,
        title="Student Correction Report",
        story=story,
        context="  -  ".join(context_bits),
        label="CORRECTION REPORT",
        eyebrow=eyebrow,
        doc_id=(f"{doc_prefix}{result['id'][:8]}" if result.get("id") else ""),
        generated_at=(datetime.fromtimestamp(generated_at) if generated_at
                      else None),
    )
    return report.build()
