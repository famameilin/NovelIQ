"""
Phase3 对话归属测试 — 使用正式 AnnotationClient 入口测试 LLM

创建时间: 2026-03-31
创建者: TraeAI
任务: fix-phase3-speaker-identity-clue-mismatch
说明: 使用正式 API 入口测试修复后的对话归属功能，对比旧结果

测试 chunk：21（赤甲卫场景）和 25（白芷首次出场）
"""

import sys
import os
import time
import json
from datetime import datetime

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, _project_root)

from dotenv import load_dotenv
load_dotenv(os.path.join(_project_root, '.env'))

import src.config
from src.models.annotation import AnnotationClient
from src.models.local.annotation.phase3 import (
    extract_dialogues_from_text,
    compute_dialogue_lengths_with_llm,
)
from src.models.local.schema import DialogueRecord, QuoteCandidate
from src.storage.db import get_engine, provide_session
from sqlalchemy import text as sa_text


CHUNK_21_TEXT = """赤甲卫站在城门口，目光如炬，扫视着每一个过往的行人。

"站住。"一个沙哑的声音从队伍中传出。

赤甲卫走上前来，面具后的眼神锐利如鹰。"伯安？"他沉声问道，"还是该称呼你一声贺统领？"

灰衣人微微欠身，姿态恭敬。"属下只是普通商人，不敢当统领之名。"

"你当得。"赤甲卫冷声道，"三年前你临阵脱逃，导致赤甲卫损失惨重。今日既然让我撞见，就别想活着离开。"

"大人明鉴，"灰衣人急忙辩解，"属下当时确有苦衷——"

"苦衷？"赤甲卫打断他，"贺重明，你的苦衷就是抛下兄弟们独自逃生！"

灰衣人终于不再掩饰，直起身来，目光中闪过一丝决然。"既然大人执意追究，那属下也不必再隐瞒。"他缓缓开口，"不错，我是贺重明。但当年的事，并非你所知的那样。"

"哦？"赤甲卫的语气中多了几分玩味，"那你说说，当年究竟发生了什么？"

贺重明深吸一口气，正要开口解释，忽然一个声音从人群中响起——

"贺大哥，原来你在这里！"

赤甲卫转头看去，只见一个年轻女子正朝这边跑来，脸上的表情又惊又喜。"贺大哥，我找了你很久！"

"白芷？"贺重明皱起眉头，"你怎么来了？"

"我——"白芷刚要回答，忽然看到赤甲卫，脸色骤变，"这些人是——"

"不必多言。"贺重明一把拉过白芷，挡在自己身前，"赤甲卫的大人，这是我妹妹白芷，与此事无关，请放她离开。"

"妹妹？"赤甲卫面具后的眼神闪烁，"贺重明，你什么时候多了个妹妹？"

"回大人，"白芷抢先开口，"民女白芷，是贺大哥的义妹。我们自幼相识，情同手足。"

赤甲卫沉默片刻，忽然冷笑一声。"好一个情同手足。贺重明，你倒是越来越会拉拢人心了。"

"大人，"贺重明沉声道，"当年的事，我愿意一五一十解释清楚。但请先让我妹妹离开，她确实与赤甲卫的旧事无关。"

"赵哥，你怎么看？"赤甲卫忽然转向身旁的另一名护卫。

被称为赵哥的护卫上前一步，声音低沉。"大人，此事恐怕另有隐情。不如先把他们都带回去，仔细审问再做定夺。"

"也好。"赤甲卫点点头，"来人，将贺重明及其同伙全部拿下！"

"且慢！"贺重明高声道，"大人若要动手，在下不敢反抗，但有一事相求——"

"说。"

"请大人听在下一言，"贺重明的目光中透出恳切，"三年前那场战役，粮草被烧、援军迷路，这一切都是有人设计陷害。在下并非临阵脱逃，而是被人出卖，险些丧命。这三年来，在下一直在暗中调查，终于找到了一些线索——"

"够了！"赤甲卫厉声打断，"你以为我会相信你的鬼话吗？来人，动手！"

场面一时僵住，贺重明护住白芷，神色凝重。"既然大人执意如此，在下只好得罪了。"

"就凭你？"赤甲卫不屑地哼了一声，"三年前你就不是我的对手，现在更不可能。"

"那就试试看吧。"贺重明说罢，突然拉着白芷转身就跑。

"追！"赤甲卫一声令下，赤甲卫们立刻追了上去。

"""


CHUNK_25_TEXT = """白芷拉着贺重明的袖子，眼泪在眼眶中打转。

"贺大哥，我们还是快逃吧。那个赤甲卫看起来好可怕。"

"别怕。"贺重明轻轻拍了拍白芷的手背，声音温和，"有贺大哥在，不会让人伤害你的。"

"可是——"

"嘘。"贺重明竖起手指，示意她安静。

两人躲在一处破庙里，外面传来赤甲卫巡逻的脚步声。贺重明屏住呼吸，将白芷护在身后。

脚步声渐渐远去，贺重明这才松了口气。

"贺大哥，"白芷压低声音，"那个赤甲卫说你是逃兵，是真的吗？"

"不是。"贺重明的回答简短而坚定。

"可是他说你临阵脱逃——"

"白芷。"贺重明转过身来，目光认真地看着她，"你相信贺大哥吗？"

"当然相信！"白芷毫不犹豫地说，"贺大哥说什么我都信。"

"那就好。"贺重明露出一个微笑，"等这件事结束，贺大哥带你离开这里，去一个没有人认识我们的地方，重新开始新的生活。"

"真的吗？"白芷的眼睛亮了起来，"我们再也不回来了吗？"

"再也不回来了。"

"那太好了！"白芷开心地拍着手，"我早就想离开这里了。贺大哥，你知道吗？自从爹娘去世后，我就一直跟着爷爷生活。后来爷爷也不在了，我就一个人孤零零的——"

"我知道。"贺重明轻轻叹了口气，"你受苦了。"

"不苦。"白芷摇摇头，"只要能跟贺大哥在一起，什么苦我都能吃。"

贺重明沉默片刻，忽然问道："白芷，你还记得你爷爷吗？"

"记得一点。"白芷想了想，"爷爷是一个很慈祥的老人。他总是给我讲精灵族的故事，说我们精灵族以前有过很辉煌的文明。"

"精灵族？"贺重明眉头微皱，"你爷爷是精灵族？"

"嗯。"白芷点点头，"我爷爷是精灵族的长老，据说活了好几百年呢。不过他从来不告诉我太多关于精灵族的事情，说是怕给我带来危险。"

"原来如此。"贺重明若有所思。

"贺大哥，"白芷忽然凑近他，压低声音，"我告诉你一个秘密，你可别告诉别人。"

"什么秘密？"

"我爷爷临终前告诉我，我们精灵族有一个神器，可以召唤风雨，移山填海。不过那个神器被藏在一个很隐蔽的地方，从来没有人找到过。"

"哦？"贺重明表现出极大的兴趣，"你知道在哪里吗？"

"不知道。"白芷摇摇头，"爷爷说只有精灵族的正统血脉才能找到那个神器。可惜我是爷爷的孙女，不是正统血脉，所以——"

说到这里，白芷的神色有些黯然。

贺重明正要开口安慰，忽然外面传来一阵喧哗声。

"搜！给我仔细搜！"

"糟了！"白芷脸色大变，"他们追上来了！"

"别慌。"贺重明神色冷静，"跟我来，我有一条秘密通道。"

"什么秘密通道？"

"跟我走就是了。"贺重明拉起白芷的手，快步向破庙后面走去。

两人穿过一条狭窄的地道，终于逃出了城。

"呼——"白芷长出一口气，"好险啊！"

"是啊。"贺重明擦了擦额头的汗水，"不过总算逃出来了。"

"贺大哥，"白芷仰头看着他，眼睛里满是崇拜，"你好厉害啊！那条秘密通道你是怎么发现的？"

贺重明微微一笑，没有回答。

"贺大哥——"白芷正要追问，忽然一个声音从远处传来——

"贺重明！白芷！你们给我站住！"

两人回头一看，顿时脸色惨白——赤甲卫已经追上来了！

"快跑！"贺重明一把拉住白芷，拼命向前跑去。

但赤甲卫的速度太快了，眼看就要被追上。

"贺大哥，你放下我吧。"白芷哭着说，"这样你就能跑得更快——"

"胡说！"贺重明厉声道，"我怎么可能丢下你！"

"可是——"

"没有可是！"贺重明握紧白芷的手，"就算死，我们也要死在一起！"

赤甲卫越来越近，贺重明的心渐渐沉了下去——

就在这时，前方忽然出现了一群人，为首的是一个身穿白衣的中年男子。

"来者何人？"白衣男子沉声问道。

"在下贺重明，"贺重明高声道，"被人追杀，还请前辈救命！"

白衣男子看了看追来的赤甲卫，又看了看贺重明和白芷，眼中闪过一丝复杂的神色。

"原来是你。"白衣男子淡淡道，"赤甲卫的人，你们回去吧。这两个人，我保了。"

"你是什么人？"赤甲卫队长喝问道，"竟敢阻拦赤甲卫执法？"

"我是什么人？"白衣男子冷笑一声，"回去告诉你们统领，就说白老弟在此。"

"白老弟？！"赤甲卫们脸色大变，面面相觑。

"走！"赤甲卫队长一声令下，带着手下迅速离去。

"多谢前辈救命之恩。"贺重明连忙行礼。

"不必客气。"白衣男子——白老弟，看了看白芷，眼中满是慈爱，"白芷，我的孩子，这些年你受苦了。"

"你——你叫我什么？"白芷愣住了。

"白芷，我是你的亲叔叔啊。"白老弟叹了口气，"你爷爷是我的哥哥。"

"""


def get_old_results_from_db(session, chunk_id: int, run_id: str) -> list[dict]:
    """从数据库获取旧结果"""
    result = session.execute(
        sa_text("""
            SELECT chunk_id, speaker, length, tone, content, identity_clue
            FROM chunk_dialogues
            WHERE chunk_id = :chunk_id AND run_id = :run_id
            ORDER BY chunk_id, id
        """),
        {"chunk_id": chunk_id, "run_id": run_id}
    )
    return [
        {
            "chunk_id": row[0],
            "speaker": row[1],
            "length": row[2],
            "tone": row[3],
            "content": row[4],
            "identity_clue": row[5],
        }
        for row in result.fetchall()
    ]


def format_comparison(
    old_results: list[dict],
    new_records: list[DialogueRecord],
    candidates: list[QuoteCandidate],
) -> dict:
    """格式化对比结果"""
    old_by_index = {i+1: r for i, r in enumerate(old_results)}
    new_by_index = {r.index: r for r in new_records}
    candidate_map = {c.index: c.content for c in candidates}

    comparison = []
    all_indices = sorted(set(old_by_index.keys()) | set(new_by_index.keys()))

    for idx in all_indices:
        old = old_by_index.get(idx, {})
        new = new_by_index.get(idx)
        content = candidate_map.get(idx, new.content if new else old.get("content", ""))

        old_speaker = old.get("speaker")
        new_speaker = new.speaker if new else None

        is_same = old_speaker == new_speaker
        is_improved = old_speaker is None and new_speaker is not None
        is_regression = old_speaker is not None and new_speaker is None

        comparison.append({
            "index": idx,
            "content": content[:30] + "..." if len(content) > 30 else content,
            "old_speaker": old_speaker,
            "new_speaker": new_speaker,
            "identity_clue": new.identity_clue if new else None,
            "is_same": is_same,
            "is_improved": is_improved,
            "is_regression": is_regression,
        })

    return comparison


def print_comparison_table(comparison: list[dict], chunk_id: int) -> None:
    """打印对比表格"""
    print(f"\n{'='*80}")
    print(f"Chunk {chunk_id} 对话归属对比结果")
    print(f"{'='*80}")
    print(f"{'Idx':<4} {'内容':<25} {'旧speaker':<12} {'新speaker':<12} {'状态':<10}")
    print(f"{'-'*80}")

    improved_count = 0
    regression_count = 0
    same_count = 0

    for item in comparison:
        status = "✓ 相同" if item["is_same"] else ("✓ 改进" if item["is_improved"] else ("✗ 回归" if item["is_regression"] else "?"))

        if item["is_improved"]:
            improved_count += 1
            status = f"✓ 改进"
        elif item["is_regression"]:
            regression_count += 1
            status = f"✗ 回归"
        else:
            same_count += 1

        old_sp = item["old_speaker"] or "(null)"
        new_sp = item["new_speaker"] or "(null)"

        print(f"{item['index']:<4} {item['content']:<25} {old_sp:<12} {new_sp:<12} {status}")

        if item["identity_clue"]:
            print(f"     └── clue: {item['identity_clue'][:50]}...")

    print(f"{'-'*80}")
    print(f"统计: 相同={same_count}, 改进={improved_count}, 回归={regression_count}, 总计={len(comparison)}")
    print(f"改进率: {improved_count/len(comparison)*100:.1f}%" if comparison else "无数据")


@provide_session
def run_test(session) -> None:
    """运行测试"""
    print("Phase3 对话归属 LLM 测试")
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)

    client = AnnotationClient(task_type="annotation")

    test_cases = [
        {
            "chunk_id": 21,
            "text": CHUNK_21_TEXT,
            "known_chars": ["伯安", "贺重明", "赤甲卫", "赵哥"],
            "run_id": "test-phase3-fix-20260331",
        },
        {
            "chunk_id": 25,
            "text": CHUNK_25_TEXT,
            "known_chars": ["伯安", "贺重明", "白芷", "白老弟"],
            "run_id": "test-phase3-fix-20260331",
        },
    ]

    for test_case in test_cases:
        chunk_id = test_case["chunk_id"]
        text = test_case["text"]
        known_chars = test_case["known_chars"]

        print(f"\n{'#'*80}")
        print(f"# 测试 Chunk {chunk_id}")
        print(f"# 已知角色: {known_chars}")
        print(f"# 文本长度: {len(text)} 字符")
        print(f"# 预计对话数: ~{text.count(chr(0x201C)) + text.count(chr(0x201D))} 条")

        candidates = extract_dialogues_from_text(text, context_chars=50)
        print(f"# 提取到候选: {len(candidates)} 条")

        old_results = get_old_results_from_db(session, chunk_id, "prod-run-20260315")
        if old_results:
            print(f"# 数据库旧结果: {len(old_results)} 条")

        start_time = time.time()
        try:
            result = compute_dialogue_lengths_with_llm(
                client=client,
                text=text,
                alias_map=None,
                chunk_id=chunk_id,
                run_id=test_case["run_id"],
                known_characters=known_chars,
                return_tones=True,
                return_evidences=True,
                return_identity_clues=True,
            )
            duration = time.time() - start_time

            if len(result) == 6:
                speaker_lengths, attribution, dialogues, tones, evidences, identity_clues = result
            elif len(result) == 5:
                speaker_lengths, attribution, dialogues, tones, evidences = result
                identity_clues = {}
            elif len(result) == 4:
                speaker_lengths, attribution, dialogues, tones = result
                evidences = {}
                identity_clues = {}
            else:
                speaker_lengths, attribution, dialogues = result
                tones = {}
                evidences = {}
                identity_clues = {}

            print(f"\n## LLM 调用成功 (耗时 {duration:.1f}s)")
            print(f"## 说话者长度: {speaker_lengths}")
            print(f"## 归属映射: {attribution}")

            records = []
            for idx, content in dialogues:
                record = DialogueRecord(
                    index=idx,
                    content=content,
                    is_dialogue=True,
                    speaker=attribution.get(idx),
                    tone=tones.get(idx),
                    evidence=evidences.get(idx),
                    identity_clue=identity_clues.get(idx),
                )
                records.append(record)

            if old_results:
                comparison = format_comparison(old_results, records, candidates)
                print_comparison_table(comparison, chunk_id)
            else:
                print("\n## 新结果（无旧结果对比）:")
                for idx, content in dialogues:
                    speaker = attribution.get(idx)
                    clue = identity_clues.get(idx)
                    print(f"  [{idx}] {speaker or '(null)'}: {content[:30]}...")
                    if clue:
                        print(f"      clue: {clue}")

        except Exception as e:
            print(f"\n## LLM 调用失败: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*80}")
    print("测试完成")
    print(f"{'='*80}")


if __name__ == "__main__":
    run_test()