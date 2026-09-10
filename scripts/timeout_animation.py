"""Render an evidence-backed explainer; no API calls or application DB writes."""

import hashlib
import json
from pathlib import Path

from manim import (
    DOWN,
    LEFT,
    RIGHT,
    UP,
    Arrow,
    Create,
    Dot,
    FadeIn,
    FadeOut,
    Line,
    RoundedRectangle,
    Scene,
    Text,
    VGroup,
    config,
)

ROOT = Path(__file__).resolve().parents[1]
BG = "#101F30"
FG = "#F2F0E9"
MUTED = "#AABCCD"
TEAL = "#53D6BF"
AMBER = "#FFCA79"
RED = "#FF8791"
FONT = "Microsoft JhengHei"


def evidence():
    source = ROOT / "docs/demo/checkpoints.json"
    stages = {s["stage"]: s["bookings"] for s in json.loads(source.read_text("utf-8"))}
    before = stages["03-reversed-no-extra-booking"]
    after = stages["04-lost-reply-recovered-once"]
    old = {b["id"]: b for b in before}
    new = [b for b in after if b["id"] not in old]
    assert len({b["id"] for b in after}) == len(after), "Duplicate booking IDs"
    assert len(new) == 1 and len(after) == len(before) + 1
    assert all(b == old[b["id"]] for b in after if b["id"] in old)
    assert new[0]["version"] == 1 and new[0]["status"] == "active"
    return {
        "source": "docs/demo/checkpoints.json",
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "before_count": len(before),
        "after_count": len(after),
        "added": new[0],
    }


def label(text, size=28, color=FG, width=12):
    obj = Text(text, font=FONT, font_size=size, color=color)
    if obj.width > width:
        obj.scale_to_fit_width(width)
    return obj


def card(title, subtitle, x, color=TEAL):
    box = RoundedRectangle(
        width=3.25,
        height=1.5,
        corner_radius=0.16,
        stroke_color=color,
        fill_color="#192F44",
        fill_opacity=1,
    )
    content = VGroup(label(title, 30, color, 2.9), label(subtitle, 19, MUTED, 2.9))
    content.arrange(DOWN, buff=0.2)
    return VGroup(box, content).move_to([x, 0.65, 0])


class TimeoutIsNotFailure(Scene):
    def construct(self):
        facts = evidence()
        config.background_color = BG
        self.camera.background_color = BG
        brand = label("STATEFUL SERVICE AGENT", 16, TEAL).to_corner(UP + LEFT, buff=0.4)
        tag = label("流程解說 / 合成測試證據", 16, MUTED).to_corner(UP + RIGHT, buff=0.4)
        self.add(brand, tag)

        def start(number, title, subtitle):
            group = VGroup(
                label(f"0{number} / 06", 17, TEAL).move_to([-5.65, 2.65, 0]),
                label(title, 38).move_to([0, 2.1, 0]),
                label(subtitle, 25, FG).move_to([0, -2.65, 0]),
                Line([-6.2, -3.25, 0], [6.2, -3.25, 0], color="#314659"),
                Line([-6.2, -3.25, 0], [-6.2 + 12.4 * number / 6, -3.25, 0], color=TEAL),
            )
            self.play(FadeIn(group), run_time=0.5)
            return group

        def end(group, start_time, duration):
            self.wait(max(0, duration - (self.time - start_time) - 0.5))
            # Individually animated objects remain scene roots even when later
            # grouped for layout. Remove every chapter root, not just its header.
            roots = [m for m in self.mobjects if m is not brand and m is not tag]
            self.play(*(FadeOut(m) for m in roots), run_time=0.5)
            self.clear()
            self.add(brand, tag)

        t = self.time
        g = start(1, "逾時，不等於失敗", "收到的回覆，可能落後於資料庫的真實狀態。")
        question = label("沒有收到成功回覆", 34, AMBER).move_to([0, 0.6, 0])
        answer = label("能直接再建一次預約嗎？", 36).move_to([0, -0.5, 0])
        self.play(FadeIn(question, shift=UP * 0.15), run_time=0.7)
        self.play(FadeIn(answer), run_time=0.7)
        g.add(question, answer)
        end(g, t, 6)

        t = self.time
        g = start(2, "先授權，再寫入", "模型只提議；身分、版本與確認期限由程式檢查。")
        cards = VGroup(
            card("使用者確認", "明確同意這次操作", -4.5),
            card("業務規則", "身分 · 版本 · 期限", 0),
            card("SQLite", "等待交易", 4.5),
        )
        arrows = VGroup(
            Arrow([-2.8, 0.65, 0], [-1.7, 0.65, 0], buff=0.05, color=TEAL),
            Arrow([1.7, 0.65, 0], [2.8, 0.65, 0], buff=0.05, color=TEAL),
        )
        note = label("同一個 operation_id 貫穿執行與查證", 25, MUTED).move_to([0, -1, 0])
        self.play(FadeIn(cards), Create(arrows), run_time=1)
        packet = Dot([-2.7, 0.65, 0], color=AMBER)
        self.add(packet)
        self.play(packet.animate.move_to([2.7, 0.65, 0]), run_time=1.5)
        self.play(FadeOut(packet), FadeIn(note), run_time=0.5)
        g.add(cards, arrows, note)
        end(g, t, 9)

        t = self.time
        g = start(3, "一次交易，保存兩份依據", "預約變更與提交收據，在同一個 SQLite 交易中保存。")
        boundary = RoundedRectangle(
            width=10, height=2.8, corner_radius=0.2, stroke_color=TEAL
        ).move_to([0, 0.15, 0])
        left = card("預約", "洗衣機維修 · 版本 1", -2.5)
        right = card("提交收據", "操作 ID · 預約 · 提交時間", 2.5)
        commit = label("COMMIT  /  已提交", 30, TEAL).move_to([0, -0.85, 0])
        self.play(Create(boundary), FadeIn(left), FadeIn(right), run_time=1)
        self.play(FadeIn(commit), run_time=0.7)
        g.add(boundary, left, right, commit)
        end(g, t, 9)

        t = self.time
        g = start(4, "回覆遺失，結果變得未知", "未知的是介面收到的結果；資料庫其實已經提交。")
        ui = card("介面：結果未知", "先保留原操作", -4, AMBER)
        db = card("資料庫：已提交", "預約與收據仍在", 4)
        path = Arrow([2.2, 0.65, 0], [-2.2, 0.65, 0], color=MUTED, buff=0.1)
        cross = VGroup(
            Line([-0.3, 0.35, 0], [0.3, 0.95, 0], color=RED),
            Line([-0.3, 0.95, 0], [0.3, 0.35, 0], color=RED),
        )
        note = label("回覆遺失  ≠  交易回滾", 31, AMBER).move_to([0, -1.1, 0])
        self.play(FadeIn(ui), FadeIn(db), Create(path), run_time=1)
        self.play(Create(cross), FadeIn(note), run_time=0.7)
        g.add(ui, db, path, cross, note)
        end(g, t, 8)

        t = self.time
        g = start(
            5, "查證原操作，找回提交收據", "以相同操作 ID 查證；找到已提交收據，就回傳既有結果。"
        )
        query = card("查證與恢復", "沿用原 operation_id", -4)
        receipt = card("原提交收據", "已提交 · 版本 1", 4)
        forward = Arrow([-2.2, 0.9, 0], [2.2, 0.9, 0], color=TEAL, buff=0.1)
        back = Arrow([2.2, 0.2, 0], [-2.2, 0.2, 0], color=AMBER, buff=0.1)
        note = label("不因回覆遺失而另建一筆預約", 30, TEAL).move_to([0, -1.15, 0])
        self.play(FadeIn(query), FadeIn(receipt), Create(forward), run_time=1)
        self.play(Create(back), FadeIn(note), run_time=1)
        g.add(query, receipt, forward, back, note)
        end(g, t, 9)

        t = self.time
        g = start(6, "最後，看資料庫", "這是本機 SQLite 的合成案例；不是任意外部服務的保證。")
        count = label(
            f"原有 {facts['before_count']} 筆  +  本次 1 筆  =  共 {facts['after_count']} 筆",
            40,
            TEAL,
        ).move_to([0, 0.85, 0])
        booking = facts["added"]
        detail = label(
            f"{booking['service']}  /  {booking['slot'][:10]} 14:00  /  版本 {booking['version']}",
            25,
            FG,
        ).move_to([0, -0.05, 0])
        proof = label("第 03 → 04 檢查點：原預約不變，只新增一個預約 ID", 22, MUTED).move_to(
            [0, -0.8, 0]
        )
        source = label(
            "證據：docs/demo/checkpoints.json  ·  搭配實際操作錄影查閱", 19, MUTED
        ).move_to([0, -1.45, 0])
        self.play(FadeIn(count), FadeIn(detail), run_time=1)
        self.play(FadeIn(proof), FadeIn(source), run_time=0.7)
        g.add(count, detail, proof, source)
        end(g, t, 11)


if __name__ == "__main__":
    print(json.dumps(evidence(), ensure_ascii=False, indent=2))
