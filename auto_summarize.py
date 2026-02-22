"""
自动纪要生成脚本
用法：
  python auto_summarize.py                # 处理 raw/ 中所有待处理文件
  python auto_summarize.py jeff-dean-latent-space           # 处理指定 slug
  python auto_summarize.py slug1 slug2 --force              # 强制覆盖已有纪要

依赖：pip install openai
API Key：设置环境变量 ARK_API_KEY
"""
import os
import sys
import openai
from datetime import date

RAW_DIR = 'raw'
SUMMARY_DIR = 'summaries'
TEMPLATE_PATH = 'prompts/summary_template.md'
BASE_URL = 'https://ark.cn-beijing.volces.com/api/v3'
MODEL = 'doubao-seed-2-0-pro-260215'
MAX_TOKENS = 32000


def load_template():
    with open(TEMPLATE_PATH, 'r', encoding='utf-8') as f:
        return f.read()


def find_pending():
    """找出 raw/ 里还没有对应纪要的 slug 列表"""
    os.makedirs(SUMMARY_DIR, exist_ok=True)
    raw_files = sorted(f for f in os.listdir(RAW_DIR) if f.endswith('.txt'))
    pending = []
    for raw_file in raw_files:
        slug = raw_file[:-4]
        if not os.path.exists(os.path.join(SUMMARY_DIR, f'{slug}.md')):
            pending.append(slug)
    return pending


def summarize(slug, template, client):
    """调用 OpenAI API 流式生成单篇纪要，返回完整文本"""
    raw_path = os.path.join(RAW_DIR, f'{slug}.txt')
    with open(raw_path, 'r', encoding='utf-8') as f:
        raw_content = f.read()

    today = date.today().strftime('%Y-%m-%d')

    system_prompt = (
        f'你是一位专业的播客内容整理专家。今天的日期是 {today}。\n\n'
        f'以下是生成纪要的格式规则：\n\n{template}'
    )
    user_prompt = (
        f'请根据以上规则，将下面的播客原文整理为中文纪要。\n\n'
        f'输出要求（请严格执行）：\n'
        f'1. **详细程度**：每节"详细精要"所有论点、数据、案例、推理链条必须完整覆盖，绝对不允许以"略"或省略号代替内容\n'
        f'2. **行内加粗**：一级 bullet 的论点标题必须加粗，正文中所有关键术语、专有名词、人名、产品名、具体数字、核心结论也一律用 **加粗** 标注\n'
        f'3. **分级 bullet 结构**："详细精要"必须使用嵌套 bullet：一级 bullet（`- **论点标题**：概括`）+ 二级 bullet（`  - 细节/例子/数据`），每节 3～6 个一级 bullet，每条下 2～4 条二级 bullet；**严禁写连续散文段落**\n'
        f'4. **精华片段**：每节必须附 1～2 句最具代表性的英文原文及中文译文，格式严格按模板\n'
        f'5. **专业术语表**：纪要末尾必须用 Markdown 表格列出所有专业术语，每条给出本集语境下的解释\n\n'
        f'原文内容如下：\n\n{raw_content}'
    )

    print(f'  模型：{MODEL}  |  原文：{len(raw_content):,} 字符')
    print()

    chunks = []
    stream = client.chat.completions.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ],
        stream=True,
    )
    for chunk in stream:
        text = chunk.choices[0].delta.content or ''
        print(text, end='', flush=True)
        chunks.append(text)

    print('\n')
    result = ''.join(chunks).strip()
    # 模型有时会把整个输出包在代码围栏里，自动剥除
    if result.startswith('```'):
        result = result[3:].lstrip('\n')
    if result.endswith('```'):
        result = result[:-3].rstrip('\n')
    return result


def main():
    force = '--force' in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith('--')]

    if args:
        slugs = args
        for slug in slugs:
            if not os.path.exists(os.path.join(RAW_DIR, f'{slug}.txt')):
                print(f'[错误] 找不到文件：raw/{slug}.txt')
                sys.exit(1)
        if not force:
            slugs = [s for s in slugs
                     if not os.path.exists(os.path.join(SUMMARY_DIR, f'{s}.md'))]
            if not slugs:
                print('指定文件已有纪要。若要重新生成，请加 --force 参数。')
                return
    else:
        slugs = find_pending()
        if not slugs:
            print('所有文件已有纪要，无需处理。运行 python summarize.py 查看状态。')
            return

    api_key = os.environ.get('ARK_API_KEY')
    if not api_key:
        print('[错误] 未设置 ARK_API_KEY 环境变量')
        print('  export ARK_API_KEY="..."')
        sys.exit(1)

    template = load_template()
    client = openai.OpenAI(api_key=api_key, base_url=BASE_URL)
    os.makedirs(SUMMARY_DIR, exist_ok=True)

    print(f'待处理：{len(slugs)} 篇\n')

    for i, slug in enumerate(slugs, 1):
        summary_path = os.path.join(SUMMARY_DIR, f'{slug}.md')
        print(f'[{i}/{len(slugs)}] {slug}')

        try:
            result = summarize(slug, template, client)
            with open(summary_path, 'w', encoding='utf-8') as f:
                f.write(result)
            print(f'  ✅ 已保存：{summary_path}  （{len(result):,} 字符）')
        except openai.APIStatusError as e:
            print(f'  ❌ API 错误 {e.status_code}：{e.message}')
        except Exception as e:
            print(f'  ❌ 失败：{e}')

        print()

    print('全部完成！运行 python generator.py 生成 HTML 页面。')


if __name__ == '__main__':
    main()
