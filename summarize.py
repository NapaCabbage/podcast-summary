"""
纪要辅助脚本
用法：python summarize.py
列出 raw/ 中还没有对应纪要的文件，提示你让 Claude Code 处理
"""
import os

RAW_DIR = 'raw'
SUMMARY_DIR = 'summaries'


def main():
    os.makedirs(SUMMARY_DIR, exist_ok=True)

    raw_files = [f for f in os.listdir(RAW_DIR) if f.endswith('.txt')]
    if not raw_files:
        print('raw/ 文件夹为空，请先运行：python scraper.py')
        return

    pending = []
    done = []

    for raw_file in sorted(raw_files):
        slug = raw_file.replace('.txt', '')
        summary_file = os.path.join(SUMMARY_DIR, f'{slug}.md')
        if os.path.exists(summary_file):
            done.append(slug)
        else:
            pending.append(slug)

    print(f'=== 纪要状态 ===\n')
    print(f'已完成：{len(done)} 篇')
    for slug in done:
        print(f'  ✅ {slug}')

    print(f'\n待处理：{len(pending)} 篇')
    for slug in pending:
        raw_path = os.path.join(RAW_DIR, f'{slug}.txt')
        size = os.path.getsize(raw_path)
        print(f'  ⏳ {slug}  ({size:,} 字节)')

    if pending:
        print(f'\n=== 下一步 ===')
        print('在 Claude Code 对话框中输入：')
        print()
        print('  帮我总结 raw/ 里所有待处理的文件，按照 prompts/summary_template.md 的格式生成中文纪要，保存到 summaries/ 文件夹')
        print()
        print('或者指定单个文件：')
        for slug in pending:
            print(f'  帮我总结 raw/{slug}.txt，按照 prompts/summary_template.md 的格式生成中文纪要，保存为 summaries/{slug}.md')


if __name__ == '__main__':
    main()
