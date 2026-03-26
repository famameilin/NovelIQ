from pathlib import Path
import sys
sys.path.insert(0, 'e:/projects/python-projects/novel quantitative analysis')

from src.topic.lda_model import LDATrainer, get_all_topic_words
from src.topic.preprocessor import TopicPreprocessor
from src.storage.schema import connect_db
from deprecated.storage.operations.chunk_ops import fetch_chunk_texts

conn = connect_db(Path('output/人祖传_analysis.db'))
text_tuples = fetch_chunk_texts(conn)
print(f'获取到 {len(text_tuples)} 条记录')

# fetch_chunk_texts返回的是(chunk_id, text)元组列表，取第二个元素
texts = [t[1] if isinstance(t, tuple) and len(t) > 1 else t for t in text_tuples]
print(f'文本数量: {len(texts)}')

preprocessor = TopicPreprocessor()
tokenized_docs = preprocessor.preprocess_documents(texts)

trainer = LDATrainer()
topic_model = trainer.train(tokenized_docs)

print('\n=== 主题关键词（前10个主题）===')
all_topics = get_all_topic_words(topic_model, top_n=10)
for topic_id in sorted(all_topics.keys())[:10]:
    words = all_topics[topic_id]
    word_list = [f"{w['word']}({w['weight']:.3f})" for w in words[:5]]
    print(f'主题{topic_id}: {" ".join(word_list)}')

conn.close()
