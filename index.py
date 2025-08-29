#!/usr/bin/env python3
"""
GitLab 到 GitHub 一键迁移工具

功能：
1. 获取 GitLab 用户的所有仓库（包括私有仓库）
2. 检查 GitHub 中是否已存在同名仓库
3. 完整迁移仓库代码和所有分支
4. 使用 GitHub Actions Importer 迁移 CI/CD 配置
5. 提供交互式选择界面

使用前请确保：
- 已配置 GITLAB_ACCESS_TOKEN 环境变量
- 已配置 GITHUB_ACCESS_TOKEN 环境变量  
- 已安装 gh CLI 并登录
- 已配置 GitHub Actions Importer
"""

import os
import sys
import json
import subprocess
import requests
from typing import List, Dict, Optional
import tempfile
import shutil
from pathlib import Path
import time
from urllib.parse import urlparse
from dotenv import load_dotenv

class GitLabToGitHubMigrator:
    def __init__(self):
        # 自动加载 .env（优先环境变量，不覆盖已有）
        load_dotenv(override=False)
        self.gitlab_token = os.getenv('GITLAB_ACCESS_TOKEN')
        self.github_token = os.getenv('GITHUB_ACCESS_TOKEN')
        self.gitlab_username = os.getenv('GITLAB_USERNAME', 'wuuashen')
        # 支持通过环境变量覆盖 owner，默认与登录/用户名一致
        self.github_username = os.getenv('GITHUB_OWNER') or os.getenv('GITHUB_USERNAME') or 'wuuashen'
        self.gitlab_base_url = 'https://gitlab.com'
        self.github_base_url = 'https://api.github.com'
        self.use_github_import = os.getenv('USE_GITHUB_IMPORT', '').lower() in ['1', 'true', 'yes']
        
        if not self.gitlab_token:
            print("❌ 错误: 请设置 GITLAB_ACCESS_TOKEN 环境变量")
            sys.exit(1)
        
        if not self.github_token:
            print("❌ 错误: 请设置 GITHUB_ACCESS_TOKEN 环境变量")
            sys.exit(1)
        # 让 gh CLI 与脚本使用同一 Token
        if self.github_token and not os.getenv('GH_TOKEN'):
            os.environ['GH_TOKEN'] = self.github_token

    def get_safe_repo_name(self, gitlab_repo: Dict) -> str:
        """从 GitLab 仓库信息派生安全的 GitHub 仓库名（避免空格等非法字符）"""
        # 优先使用 GitLab 的 slug/path（通常已是安全名）
        path_slug = gitlab_repo.get('path')
        if path_slug:
            return path_slug

        # 退化为从 http_url_to_repo 解析最后一段
        url = gitlab_repo.get('http_url_to_repo') or ''
        try:
            parsed = urlparse(url)
            last = Path(parsed.path).name  # like 'tvcmall-www.git'
            if last.endswith('.git'):
                last = last[:-4]
            return last.replace(' ', '-')
        except Exception:
            # 最后兜底：原 name 去空格
            return (gitlab_repo.get('name') or 'repo').replace(' ', '-')

    def _redact(self, text: str) -> str:
        if not text:
            return text
        redacted = text
        if self.github_token:
            redacted = redacted.replace(self.github_token, '***')
        return redacted

    def run_and_stream(self, cmd: List[str], cwd: Optional[str] = None, env: Optional[Dict[str, str]] = None) -> None:
        """执行命令并实时打印输出，失败抛出异常。"""
        printable = self._redact(' '.join(cmd))
        if cwd:
            print(f"    $ (cd {cwd} && {printable})")
        else:
            print(f"    $ {printable}")

        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)

        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=merged_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        output_lines: List[str] = []
        assert process.stdout is not None
        for line in process.stdout:
            print(line.rstrip())
            output_lines.append(line)

        process.wait()
        if process.returncode != 0:
            # 抛出并附带完整输出，便于上层打印
            raise subprocess.CalledProcessError(process.returncode, cmd, ''.join(output_lines))
    
    def get_gitlab_repositories(self) -> List[Dict]:
        """获取 GitLab 用户的所有仓库"""
        print("🔍 正在获取 GitLab 仓库列表...")
        
        headers = {'Authorization': f'Bearer {self.gitlab_token}'}
        repos = []
        page = 1
        
        while True:
            url = f"{self.gitlab_base_url}/api/v4/projects"
            params = {
                'owned': 'true',
                'membership': 'true', 
                'per_page': 100,
                'page': page
            }
            
            response = requests.get(url, headers=headers, params=params)
            if response.status_code != 200:
                print(f"❌ 获取 GitLab 仓库失败: {response.status_code}")
                sys.exit(1)
            
            data = response.json()
            if not data:
                break
                
            repos.extend(data)
            page += 1
        
        # 过滤出属于指定用户的仓库
        user_repos = [repo for repo in repos 
                     if repo.get('namespace', {}).get('path') == self.gitlab_username]
        
        print(f"✅ 找到 {len(user_repos)} 个 GitLab 仓库")
        return user_repos
    
    def check_github_repo_exists(self, repo_name: str) -> bool:
        """检查 GitHub 仓库是否已存在"""
        # 优先使用 gh CLI（对私有仓库更可靠）
        try:
            env = os.environ.copy()
            if self.github_token and not env.get('GH_TOKEN'):
                env['GH_TOKEN'] = self.github_token
            result = subprocess.run([
                'gh', 'repo', 'view', f"{self.github_username}/{repo_name}"
            ], capture_output=True, text=True, env=env)
            if result.returncode == 0:
                return True
        except Exception:
            pass

        # 回退到 GitHub REST API
        headers = {
            'Authorization': f'token {self.github_token}',
            'Accept': 'application/vnd.github+json'
        }
        url = f"{self.github_base_url}/repos/{self.github_username}/{repo_name}"
        try:
            response = requests.get(url, headers=headers, timeout=15)
            return response.status_code == 200
        except requests.RequestException:
            return False
    
    def has_gitlab_ci(self, project_id: str) -> Optional[str]:
        """检查项目是否有 GitLab CI 配置"""
        headers = {'Authorization': f'Bearer {self.gitlab_token}'}
        
        # 检查主要分支的 .gitlab-ci.yml
        for branch in ['master', 'main']:
            url = f"{self.gitlab_base_url}/api/v4/projects/{project_id}/repository/files/.gitlab-ci.yml"
            params = {'ref': branch}
            
            response = requests.get(url, headers=headers, params=params)
            if response.status_code == 200:
                return branch
        
        return None
    
    def display_repositories(self, repos: List[Dict]):
        """显示仓库列表供用户选择"""
        print("\n📋 GitLab 仓库列表:")
        print("=" * 80)
        
        for i, repo in enumerate(repos):
            safe_name = self.get_safe_repo_name(repo)
            visibility = "🔒 私有" if repo['visibility'] == 'private' else "🌐 公开"
            has_ci = "✅ 有CI" if self.has_gitlab_ci(repo['id']) else "❌ 无CI"
            exists_on_github = "⚠️  已存在" if self.check_github_repo_exists(safe_name) else "✨ 新建"
            
            print(f"{i+1:2d}. {repo['name']:<30} {visibility:<8} {has_ci:<8} {exists_on_github}")
            print(f"    📝 {(repo.get('description') or '无描述')[:50]}")
            print(f"    📅 最后活动: {repo['last_activity_at'][:10]}")
            print()
    
    def select_repositories(self, repos: List[Dict]) -> List[Dict]:
        """让用户选择要迁移的仓库"""
        self.display_repositories(repos)
        
        print("选择要迁移的仓库:")
        print("  输入数字选择单个仓库 (如: 1)")
        print("  输入范围选择多个仓库 (如: 1-3)")  
        print("  输入多个数字用逗号分隔 (如: 1,3,5)")
        print("  输入 'all' 选择所有仓库")
        print("  输入 'q' 退出")
        
        while True:
            selection = input("\n请选择: ").strip()
            
            if selection.lower() == 'q':
                print("👋 退出迁移")
                sys.exit(0)
            
            if selection.lower() == 'all':
                # 过滤掉在 GitHub 上已存在的仓库
                available_repos = [repo for repo in repos 
                                 if not self.check_github_repo_exists(self.get_safe_repo_name(repo))]
                if len(available_repos) < len(repos):
                    skipped = len(repos) - len(available_repos)
                    print(f"⚠️  跳过 {skipped} 个已在 GitHub 存在的仓库")
                return available_repos
            
            try:
                selected_repos = []
                
                if ',' in selection:
                    # 逗号分隔的多个选择
                    indices = [int(x.strip()) - 1 for x in selection.split(',')]
                elif '-' in selection:
                    # 范围选择
                    start, end = map(int, selection.split('-'))
                    indices = list(range(start - 1, end))
                else:
                    # 单个选择
                    indices = [int(selection) - 1]
                
                for idx in indices:
                    if 0 <= idx < len(repos):
                        repo = repos[idx]
                        if self.check_github_repo_exists(self.get_safe_repo_name(repo)):
                            print(f"⚠️  跳过 {repo['name']}: GitHub 上已存在同名仓库")
                        else:
                            selected_repos.append(repo)
                    else:
                        print(f"❌ 无效索引: {idx + 1}")
                        break
                else:
                    if selected_repos:
                        return selected_repos
                    else:
                        print("❌ 没有选择有效的仓库")
                        
            except ValueError:
                print("❌ 输入格式错误，请重试")
    
    def create_github_repo(self, name: str, description: str, is_private: bool) -> bool:
        """在 GitHub 创建仓库"""
        print(f"📝 创建 GitHub 仓库: {name}")
        
        # 若已存在则直接跳过创建
        if self.check_github_repo_exists(name):
            print(f"✅ GitHub 仓库已存在，跳过创建: https://github.com/{self.github_username}/{name}")
            return True
        
        cmd = [
            'gh', 'repo', 'create', f"{self.github_username}/{name}",
            '--description', description or f"从 GitLab 迁移的仓库",
            '--clone=false'
        ]
        
        if is_private:
            cmd.append('--private')
        else:
            cmd.append('--public')
        
        try:
            env = os.environ.copy()
            if self.github_token and not env.get('GH_TOKEN'):
                env['GH_TOKEN'] = self.github_token
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)
            print(f"✅ GitHub 仓库创建成功: https://github.com/{self.github_username}/{name}")
            return True
        except subprocess.CalledProcessError as e:
            msg = (e.stderr or e.stdout or str(e)).strip()
            # 如果提示名称已存在，则视为已存在并继续
            if 'Name already exists on this account' in msg or 'name already exists on this account' in msg.lower():
                print(f"⚠️  仓库已存在，跳过创建: https://github.com/{self.github_username}/{name}")
                return True
            print(f"❌ 创建 GitHub 仓库失败: {msg}")
            return False
    
    def migrate_repository_code(self, gitlab_repo: Dict) -> bool:
        """迁移仓库代码和所有分支"""
        repo_name = gitlab_repo['name']
        safe_name = self.get_safe_repo_name(gitlab_repo)
        gitlab_url = gitlab_repo['http_url_to_repo']
        # 使用 PAT 基本认证：username:token，避免 401/128
        github_url = f"https://{self.github_username}:{self.github_token}@github.com/{self.github_username}/{safe_name}.git"
        
        print(f"📦 迁移代码: {repo_name}")
        
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_path = Path(temp_dir) / repo_name
            
            try:
                # 1. 克隆 GitLab 仓库（镜像克隆，包含所有分支和标签）
                print("  🔄 克隆 GitLab 仓库（包含所有分支）...")
                self.run_and_stream([
                    'git', 'clone', '--mirror', gitlab_url, str(repo_path)
                ])
                
                # 2. 重新配置 GitHub 远程仓库（确保 origin 指向目标仓库）
                print("  🔗 设置 GitHub 远程仓库...")
                # 尝试移除已有 origin（忽略失败）
                subprocess.run([
                    'git', '-C', str(repo_path), 'remote', 'rm', 'origin'
                ], capture_output=True)
                # 新增 origin 指向 GitHub
                self.run_and_stream([
                    'git', '-C', str(repo_path), 'remote', 'add', 'origin', github_url
                ])
                
                # 3. 推送所有分支和标签到 GitHub
                print("  🚀 推送所有分支和标签到 GitHub...")
                env = os.environ.copy()
                env['GIT_TERMINAL_PROMPT'] = '0'
                self.run_and_stream([
                    'git', '-C', str(repo_path), 'push', '--mirror'
                ], env=env)
                
                print(f"  ✅ {repo_name} 代码迁移完成")
                return True
                
            except subprocess.CalledProcessError as e:
                detail = e.output if hasattr(e, 'output') else str(e)
                print(f"  ❌ {repo_name} 代码迁移失败: {detail}")
                return False

    def migrate_repository_via_github_import(self, gitlab_repo: Dict) -> bool:
        """使用 GitHub Import API 无需本地克隆地迁移代码"""
        repo_name = gitlab_repo['name']
        source_url = gitlab_repo['http_url_to_repo']
        # 将 GitLab Token 嵌入 URL，供 GitHub Import 服务访问私有仓库
        # 形如: https://oauth2:TOKEN@gitlab.com/owner/repo.git
        if source_url.startswith('https://'):
            source_url_with_token = source_url.replace(
                'https://', f"https://oauth2:{self.gitlab_token}@", 1
            )
        else:
            # 对于异常情况，直接拼接（极少发生）
            source_url_with_token = f"https://oauth2:{self.gitlab_token}@{source_url}"

        print(f"📦 通过 GitHub Import API 迁移代码: {repo_name}")

        headers = {
            'Authorization': f'token {self.github_token}',
            'Accept': 'application/vnd.github+json'
        }
        import_url = f"{self.github_base_url}/repos/{self.github_username}/{repo_name}/import"

        try:
            # 1) 发起导入
            payload = {
                'vcs': 'git',
                'vcs_url': source_url_with_token
            }
            resp = requests.put(import_url, headers=headers, json=payload, timeout=30)
            if resp.status_code not in [201, 202]:
                print(f"  ❌ 启动导入失败: {resp.status_code} {resp.text}")
                return False

            # 2) 轮询状态直到完成或失败
            for _ in range(120):  # 最长约2分钟
                status_resp = requests.get(import_url, headers=headers, timeout=15)
                if status_resp.status_code != 200:
                    print(f"  ❌ 查询导入状态失败: {status_resp.status_code} {status_resp.text}")
                    return False
                data = status_resp.json()
                status = data.get('status')
                if status in ['complete']:  # 完成
                    print(f"  ✅ {repo_name} 代码迁移完成（Import API）")
                    return True
                if status in ['error', 'failed']:  # 失败
                    print(f"  ❌ {repo_name} 代码迁移失败（Import API）: {data}")
                    return False
                time.sleep(1)

            print(f"  ❌ {repo_name} 代码迁移超时（Import API）")
            return False
        except requests.RequestException as e:
            print(f"  ❌ {repo_name} 代码迁移请求异常（Import API）: {e}")
            return False
    
    def migrate_ci_cd(self, gitlab_repo: Dict, output_dir: str) -> bool:
        """迁移 CI/CD 配置"""
        repo_name = gitlab_repo['name']
        safe_name = self.get_safe_repo_name(gitlab_repo)
        ci_branch = self.has_gitlab_ci(gitlab_repo['id'])
        
        if not ci_branch:
            print(f"  ℹ️  {repo_name} 无 CI 配置，跳过")
            return True
        
        print(f"  🔧 迁移 CI/CD 配置: {repo_name}")
        
        try:
            # 使用 GitHub Actions Importer 进行 CI/CD 迁移
            cmd = [
                'gh', 'actions-importer', 'migrate', 'gitlab',
                '--project', repo_name,
                '--namespace', self.gitlab_username,
                '--target-url', f"https://github.com/{self.github_username}/{safe_name}",
                '--output-dir', output_dir
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            print(f"  ✅ {repo_name} CI/CD 迁移完成")
            return True
            
        except subprocess.CalledProcessError as e:
            print(f"  ⚠️  {repo_name} CI/CD 迁移失败，但代码迁移已完成")
            print(f"     错误信息: {e.stderr}")
            return False
    
    def migrate_repositories(self, repos: List[Dict]):
        """执行批量迁移"""
        total = len(repos)
        successful_code = 0
        succeeded_repos_safe: List[str] = []
        
        # 创建输出目录
        output_dir = './migration-output'
        os.makedirs(output_dir, exist_ok=True)
        
        print(f"\n🚀 开始迁移 {total} 个仓库...")
        print("=" * 80)
        
        failed_repos = []
        for i, repo in enumerate(repos, 1):
            repo_name = repo['name']
            safe_name = self.get_safe_repo_name(repo)
            is_private = repo['visibility'] == 'private'
            description = repo.get('description') or ''
            
            print(f"\n[{i}/{total}] 处理仓库: {repo_name}")
            
            # 1. 创建 GitHub 仓库
            if not self.create_github_repo(safe_name, description, is_private):
                failed_repos.append(repo_name)
                continue
            
            # 2. 迁移代码（两种模式）
            code_ok = False
            if self.use_github_import:
                code_ok = self.migrate_repository_via_github_import(repo)
            else:
                code_ok = self.migrate_repository_code(repo)

            if code_ok:
                successful_code += 1
                succeeded_repos_safe.append(safe_name)
                
                # 不再迁移 CI/CD（按用户要求关闭）
            else:
                failed_repos.append(repo_name)
        
        # 打印总结
        print("\n" + "=" * 80)
        if successful_code == total and total > 0:
            print("🎉 迁移完成（全部成功）!")
        elif successful_code > 0:
            print("⚠️  迁移完成（部分失败）!")
        else:
            print("❌ 迁移失败（全部失败）!")

        print(f"📊 统计:")
        print(f"   代码迁移成功: {successful_code}/{total}")
        print(f"   输出目录: {output_dir}")

        if failed_repos:
            print(f"\n❗ 失败的仓库:")
            for name in failed_repos:
                print(f"   - {name}")
        
        # 列出新建的 GitHub 仓库（仅列出成功项）
        if succeeded_repos_safe:
            print(f"\n✨ 新建的 GitHub 仓库:")
            for name in succeeded_repos_safe:
                print(f"   https://github.com/{self.github_username}/{name}")

        # 根据结果设置退出码：有失败则非 0
        exit_code = 0 if successful_code == total and total > 0 else 1
        sys.exit(exit_code)

def main():
    print("🚀 GitLab 到 GitHub 一键迁移工具")
    print("=" * 50)
    
    migrator = GitLabToGitHubMigrator()
    
    # 1. 获取 GitLab 仓库
    repos = migrator.get_gitlab_repositories()
    if not repos:
        print("❌ 没有找到任何仓库")
        return
    
    # 2. 用户选择要迁移的仓库
    selected_repos = migrator.select_repositories(repos)
    if not selected_repos:
        print("❌ 没有选择任何仓库")
        return
    
    # 3. 确认迁移
    print(f"\n📋 将迁移以下 {len(selected_repos)} 个仓库:")
    for repo in selected_repos:
        print(f"   - {repo['name']} ({'私有' if repo['visibility'] == 'private' else '公开'})")
    
    confirm = input(f"\n确认开始迁移? (y/N): ").strip().lower()
    if confirm not in ['y', 'yes']:
        print("👋 取消迁移")
        return
    
    # 4. 执行迁移
    migrator.migrate_repositories(selected_repos)

if __name__ == "__main__":
    main()
