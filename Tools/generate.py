"""使用 protoc 为外部插件 v3 生成 Python 或 C++ 类型。"""
import argparse
import logging
import pathlib
import subprocess


def main():
    """为所选语言生成独立输出，并附带 Python 客户端示例。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--language', choices=('python', 'cpp'), default='python')
    parser.add_argument('--output', type=pathlib.Path)
    parser.add_argument('--protoc', default='protoc')
    arguments = parser.parse_args()
    root = pathlib.Path(__file__).resolve().parents[1]
    output = (arguments.output or root / 'target' / arguments.language).resolve()
    output.mkdir(parents=True, exist_ok=True)
    command = [arguments.protoc, f'--proto_path={root}', f'--{arguments.language}_out={output}',
               str(root / 'external_plugin.proto')]
    logging.info('生成协议类型: %s', ' '.join(command))
    subprocess.run(command, check=True)
    if arguments.language == 'python':
        import shutil
        shutil.copy2(root / 'Examples/sdk-client.py', output / 'sdk-client.py')
        shutil.copy2(root / 'Examples/remote-client.py', output / 'remote-client.py')
    logging.info('协议生成完成: %s', output)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    try:
        main()
    except Exception:
        logging.exception('协议生成失败')
        raise SystemExit(1)
