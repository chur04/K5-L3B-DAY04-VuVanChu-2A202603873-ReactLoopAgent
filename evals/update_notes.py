"""Update evidence-based notes and checkpoint status without calling any API."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[1]
NOTES_START = "<!-- EVAL_COMPARISON_START -->"
NOTES_END = "<!-- EVAL_COMPARISON_END -->"
CP_START = "<!-- LOCAL_PROGRESS_START -->"
CP_END = "<!-- LOCAL_PROGRESS_END -->"


def scored(case):
    grade = case.get("grade", {})
    return grade.get("status") == "scored" and grade.get("score") is not None


def metrics(report):
    agent_usage = [u for c in report["cases"] for u in c["result"].get("usage", [])]
    judge_usage = [c["grade"].get("judge_usage", {}) for c in report["cases"]]
    return {
        "agent_calls": sum(t.get("event") == "model" for c in report["cases"]
                           for t in c["result"].get("trace", [])),
        "judge_calls": sum(bool(u) for u in judge_usage),
        "agent_tokens": sum(u.get("total_tokens", 0) for u in agent_usage),
        "judge_tokens": sum(u.get("total_tokens", 0) for u in judge_usage),
    }


def replace_section(path, start, end, body, allow_append=False):
    original = path.read_text(encoding="utf-8")
    if start not in original and end not in original and allow_append:
        updated = original.rstrip() + "\n\n" + start + "\n" + body.rstrip() + "\n" + end + "\n"
    else:
        if original.count(start) != 1 or original.count(end) != 1:
            raise ValueError(f"Expected exactly one marker pair in {path.name}")
        prefix, rest = original.split(start, 1)
        _, suffix = rest.split(end, 1)
        updated = prefix + start + "\n" + body.rstrip() + "\n" + end + suffix
    if updated != original:
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(updated, encoding="utf-8")
        temporary.replace(path)


def render_comparison(before, after, timestamp):
    before_cases = {c["id"]: c for c in before["cases"]}
    after_cases = {c["id"]: c for c in after["cases"]}
    n = sum(scored(c) for c in after["cases"])
    full = n == 22 and after["summary"].get("score_0_100") is not None
    b, a = metrics(before), metrics(after)
    h7 = after_cases["H7"]
    after_score = str(after["summary"]["score_0_100"]) + "/100" if full else f"Chưa có: mới chấm {n}/22"
    h7_score = str(h7["grade"]["score"]) + "/100" if scored(h7) else "Chưa chấm trong bộ đầy đủ"
    rows = [
        f"Cập nhật: {timestamp}.",
        "",
        "Cấu hình hai report giống nhau: provider/judge_provider = groq; "
        "model/judge_model = openai/gpt-oss-20b; max_steps = 8; dataset = core. "
        "Dùng cùng fixtures của đề.",
        "",
        "| Chỉ số | eval_before.json | eval_after.json |",
        "|---|---:|---:|",
        f"| Số case đã chấm | 22/22 | {n}/22 |",
        f"| Điểm tổng | {before['summary']['score_0_100']}/100 | {after_score} |",
        f"| Điểm H7 | {before_cases['H7']['grade']['score']}/100 | {h7_score} |",
        f"| Model calls agent đã có response trong trace | {b['agent_calls']} | {a['agent_calls']} |",
        f"| Judge calls có usage được lưu | {b['judge_calls']} | {a['judge_calls']} |",
        f"| Token agent được lưu | {b['agent_tokens']:,} | {a['agent_tokens']:,} |",
        f"| Token judge được lưu | {b['judge_tokens']:,} | {a['judge_tokens']:,} |",
        f"| Tổng token được lưu | {b['agent_tokens'] + b['judge_tokens']:,} | {a['agent_tokens'] + a['judge_tokens']:,} |",
        "| Chi phí tiền tệ | Không có dữ liệu | Không có dữ liệu |",
        "",
    ]
    if full:
        delta = round(after["summary"]["score_0_100"] - before["summary"]["score_0_100"], 2)
        rows.append(f"Bộ sau đã chấm đủ 22 case. Chênh lệch điểm tổng: {delta:+.2f} điểm. "
                    "Đây là so sánh hai bộ kết quả được lưu, chưa chứng minh tính ổn định.")
    else:
        pending = ", ".join(c["id"] for c in after["cases"] if not scored(c))
        rows.append(f"CP6 chưa hoàn thành. Còn chưa chấm: {pending}. "
                    "Không dùng partial_mean_0_100 làm điểm tổng và chưa kết luận bộ sau tốt hơn bộ trước. "
                    "Các số calls/token ở cột sau còn là số liệu chưa đủ bộ; không dùng để kết luận tiết kiệm token.")
    rows += ["", "### Điểm từng case", "", "| Case | Trước | Sau | Chênh lệch |", "|---|---:|---:|---:|"]
    for case in after["cases"]:
        old = before_cases[case["id"]]["grade"].get("score")
        new = case["grade"].get("score") if scored(case) else None
        delta = f"{new - old:+}" if new is not None and old is not None else "—"
        rows.append(f"| {case['id']} | {old} | {new if new is not None else 'Chưa chấm'} | {delta} |")
    rows += ["", "### Kết quả lỗi đã chọn và lỗi còn lại", ""]
    if scored(h7):
        rows += [
            f"H7 trong bộ đầy đủ: {h7['grade']['score']}/100; trạng thái agent: {h7['result']['status']}. "
            "Cần đối chiếu trực tiếp câu trả lời dưới đây với lỗi timeout ở trace:",
            "",
            *["> " + line for line in h7["result"].get("answer", "").splitlines()],
            "",
            "Nhận xét judge H7: " + h7["grade"].get("reason", "Không có nhận xét."),
        ]
    else:
        rows.append("Lỗi H7 đã có bằng chứng cải thiện ở lần kiểm tra riêng (50 → 100). "
                    "Chưa xác nhận kết quả H7 của bộ đầy đủ; không nhập điểm kiểm tra riêng vào bảng trên.")
    events = [(c["id"], t["step"]) for c in after["cases"]
              for t in c["result"].get("trace", []) if t.get("event") == "validation_missing_source"]
    rows += ["", "Kiểm tra URL đã phát hiện câu trả lời thiếu nguồn tại: " +
             (", ".join(f"{case_id}/bước {step}" for case_id, step in events) if events else "chưa có event trong kết quả đang lưu") + "."]
    if scored(after_cases["A1"]):
        rows += ["", "A1: 0 → " + str(after_cases["A1"]["grade"]["score"]) +
                 " điểm. Lần trước hết max_steps; lần sau đã có final answer. "
                 "Không quy toàn bộ thay đổi này cho source gate hay prompt vì trace và lựa chọn tool cũng thay đổi."]
    below = [c for c in after["cases"] if scored(c) and c["grade"]["score"] < 100]
    if below:
        rows += ["", "Các hạn chế còn được judge ghi nhận (đề xuất của judge cần được kiểm chứng):"]
        rows.append("")
        for case in below:
            suggestion = case["grade"].get("improvement") or case["grade"].get("reason", "")
            suggestion = " ".join(suggestion.split())
            rows.append(f"- {case['id']} ({case['grade']['score']}/100): {suggestion}")
    regressions = [c["id"] for c in after["cases"] if scored(c)
                   and c["grade"]["score"] < before_cases[c["id"]]["grade"]["score"]]
    rows += ["", "Các case có điểm sau thấp hơn trước trong phần đã chấm: " +
             (", ".join(regressions) if regressions else "chưa có") +
             ". Giữ nguyên các điểm này, không chạy lại case đã scored chỉ để chọn điểm cao hơn."]
    return "\n".join(rows)


def render_checkpoints(after, timestamp):
    n = sum(scored(c) for c in after["cases"])
    full = n == 22 and after["summary"].get("score_0_100") is not None
    cp6 = ("Đã có 22/22 case, điểm tổng " + str(after["summary"]["score_0_100"]) +
           "/100; mục 4 NOTES đã cập nhật. Cần đọc lại trước khi nộp.") if full else (
           f"Đang chờ quota Groq; đã lưu {n}/22 case, điểm tổng còn null. "
           "Lượt chạy nền và tiến trình tiếp tục chỉ xử lý case chưa scored.")
    return "\n".join([
        "## Tiến độ thực tế của bài làm",
        "",
        f"Cập nhật: {timestamp}. Bảng này bổ sung tiến độ; các yêu cầu CP1–CP7 ở trên giữ nguyên.",
        "",
        "| Checkpoint | Tiến độ | Bằng chứng / việc còn lại |",
        "|---|---|---|",
        "| CP1 | Đã làm | Hai status tools đã chạy; .env được bỏ qua bởi Git. Remote đúng mẫu tên; GitHub API không đăng nhập trả private=false (11/11/2026). Chưa push commit mới. |",
        "| CP2 | Đã làm | agent.py có vòng model → tool → model; các case đã scored có câu trả lời và trace thật. |",
        "| CP3 | Đã làm | Xử lý JSON lỗi, mọi tool call/ID, max_steps, lỗi provider, finish bất thường và trace. Lần kiểm tra offline gần nhất: 57 tests pass. |",
        "| CP4 | Đã làm | eval_before.json đủ 22/22, điểm 88.41/100. Đã chọn lỗi H7 = 50 và A1 = 0 để phân tích. |",
        "| CP5 | Đã làm | Prompt xử lý timeout/yêu cầu bịa, gate URL, kiểm tra finish. NOTES mục 1–3 có evidence thật. |",
        f"| CP6 | {'Đã có kết quả; cần đọc lại' if full else 'Chưa xong'} | {cp6} |",
        "| CP7 | Đã chuẩn bị demo; chưa nộp | NOTES có kịch bản demo E4/H7 và giải thích loop. Chưa xác nhận demo trực tiếp, push commit mới hoặc nộp LMS. |",
        "",
        "### Việc cần chốt",
        "",
        ("- [x] Hai report đã chấm đủ 22/22 và có điểm tổng." if full else
         f"- [ ] Chờ eval_after.json chấm đủ 22/22 (hiện {n}/22); không dùng điểm trung bình một phần để nộp."),
        "- [x] Hai report có cùng provider, agent model, judge model, max_steps và dataset.",
        "- [x] NOTES đã có đủ 5 mục; phần so sánh phân biệt rõ kết quả đủ bộ và kết quả đang chờ.",
        "- [x] Lần kiểm tra offline gần nhất: 57 tests pass; fixtures/cases/scenarios/grading/rubric không được sửa để tăng điểm.",
        "- [x] Git không track .env; tên repo/remote đúng mẫu L3B.",
        "- [ ] Đọc lại NOTES và kết quả; giải thích được code và trace khi demo.",
        "- [x] Repo public: GitHub API không đăng nhập xác nhận private=false ngày 11/11/2026.",
        "- [ ] Commit/push phần hoàn chỉnh và nộp link LMS.",
        "",
        "Không cần làm bonus để hoàn thành bài chính. Không đánh dấu đã push hoặc đã nộp khi chưa có bằng chứng.",
    ])


def update():
    paths = [ROOT / "eval_before.json", ROOT / "eval_after.json"]
    raw = [p.read_bytes() for p in paths]
    before, after = [json.loads(data) for data in raw]
    ids = {f"E{i}" for i in range(1, 7)} | {f"A{i}" for i in range(1, 9)} | {f"H{i}" for i in range(1, 9)}
    for report in (before, after):
        if len(report["cases"]) != 22 or {c["id"] for c in report["cases"]} != ids:
            raise ValueError("Expected the complete core case list; refusing to update notes.")
    if before["config"] != after["config"]:
        raise ValueError("Before/after configurations differ; refusing to compare them.")
    timestamp = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S GMT+7")
    replace_section(ROOT / "NOTES.md", NOTES_START, NOTES_END,
                    render_comparison(before, after, timestamp))
    replace_section(ROOT / "CHECKPOINTS.md", CP_START, CP_END,
                    render_checkpoints(after, timestamp), allow_append=True)
    n = sum(scored(c) for c in after["cases"])
    print(f"Updated NOTES.md and CHECKPOINTS.md from saved results: {n}/22 scored.", flush=True)
    complete = n == 22 and after["summary"].get("score_0_100") is not None
    return hashlib.sha256(b"\0".join(raw)).digest(), complete


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true",
                        help="Refresh marked sections when reports change; stop when all 22 cases are scored.")
    args = parser.parse_args()
    previous = None
    while True:
        try:
            raw = [p.read_bytes() for p in (ROOT / "eval_before.json", ROOT / "eval_after.json")]
            digest = hashlib.sha256(b"\0".join(raw)).digest()
            if digest != previous:
                previous, complete = update()
                if complete or not args.watch:
                    return 0
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f"Notes update postponed: {type(exc).__name__}: {exc}", flush=True)
            if not args.watch:
                return 1
        time.sleep(60)


if __name__ == "__main__":
    raise SystemExit(main())
