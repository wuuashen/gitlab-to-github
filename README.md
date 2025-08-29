# GitLab 到 GitHub 一键迁移工具
![alt text](<CleanShot 2025-08-29 at 10.35.34@2x.png>)
## 功能特性

✅ **完整功能**
- 获取 GitLab 所有仓库（包括私有仓库）
- 检查 GitHub 同名仓库冲突
- 迁移完整代码和所有分支（使用 `git clone --mirror`）
- 自动迁移 CI/CD 配置（使用 GitHub Actions Importer）
- 交互式选择要迁移的仓库
- 保持仓库可见性设置（私有/公开）

✅ **用户友好**
- 进度显示和详细日志
- 自动跳过已存在的仓库
- 支持批量选择和单个选择
- 详细的错误提示和总结报告

## 前置要求

### 1. 安装依赖
```bash
# 安装 Git 与 GitHub CLI
brew install git gh                     # macOS；其他系统见 https://cli.github.com/

# 安装 Python 与依赖
python3 --version || echo "请安装 Python3"
pip3 install --upgrade pip
pip3 install -r requirements.txt  # 包含 requests 与 python-dotenv

# 安装 GitHub Actions Importer 扩展
gh extension install github/gh-actions-importer || true
```

### 2. 配置权限
```bash
# GitHub 登录（选择 HTTPS，授权 repo 权限）
gh auth login

# （可选）GitHub Actions Importer 初始化（仅迁移 CI/CD 时需要）
# gh actions-importer configure
# 选择 GitLab CI，并按提示输入 GitHub/GitLab Token
```

### 3. 设置环境变量
```bash
# GitLab Token（需要 api, read_api, read_repository 权限）
export GITLAB_ACCESS_TOKEN="你的GitLab Token"

# GitHub Token（建议与 gh 一致；脚本会将其映射到 GH_TOKEN 供 gh 使用）
export GITHUB_ACCESS_TOKEN="你的GitHub Token"
export GH_TOKEN="$GITHUB_ACCESS_TOKEN"

# 可选：显式指定账户/命名空间
export GITLAB_USERNAME="你的GitLab用户名"   # 默认从代码内置用户名
export GITHUB_OWNER="你的GitHub用户名"     # 默认从代码内置用户名

# 可选：无本地克隆模式（使用 GitHub Import API）
export USE_GITHUB_IMPORT=1  # 1/true/yes 开启；0/空 关闭
```

## 使用方法

### 1. 运行迁移脚本
```bash
python3 index.py
```

### 2. 选择要迁移的仓库
脚本会显示所有 GitLab 仓库，包括：
- 仓库名称
- 可见性（公开/私有）
- CI 状态
- GitHub 上是否已存在

支持的选择方式：
- `1` - 选择单个仓库
- `1,3,5` - 选择多个仓库
- `1-5` - 选择范围
- `all` - 选择所有（自动跳过冲突）
- `q` - 退出

### 3. 确认并开始迁移
脚本会显示迁移计划并请求确认。

## 迁移流程

每个仓库的迁移流程：

1. **创建 GitHub 仓库**
   - 使用相同名称和描述
   - 保持原有可见性设置

2. **迁移代码**
   - 使用 `git clone --mirror` 获取完整仓库
   - 推送所有分支和标签到 GitHub

3. **迁移 CI/CD**（如果存在 .gitlab-ci.yml）
   - 使用 GitHub Actions Importer 转换
   - 创建对应的 GitHub Actions 工作流

### 无本地克隆模式（可选）

如果希望避免在本地进行 `git clone --mirror`，可以启用 GitHub Import API 的服务器端导入模式：

```bash
export USE_GITHUB_IMPORT=1
python3 index.py
```

说明：
- 启用后，工具会通过 GitHub Import API 直接从 GitLab 导入仓库，无需在本地克隆和推送。
- 私有仓库会使用 `GITLAB_ACCESS_TOKEN` 进行访问。
- 若需关闭该模式，取消设置或将 `USE_GITHUB_IMPORT=0`。

### 快速开始（推荐流程，支持 .env）
```bash
# 1) 安装依赖
brew install git gh && gh extension install github/gh-actions-importer || true
pip3 install -r requirements.txt

# 2) 登录并配置
gh auth login
gh actions-importer configure  # 可选

# 3) 设置环境（任选其一）
# 3.1) 使用 .env（推荐）
cat > .env <<EOF
GITLAB_ACCESS_TOKEN=glpat_xxx
GITHUB_ACCESS_TOKEN=ghp_xxx
GITLAB_USERNAME=你的GitLab用户名
GITHUB_OWNER=你的GitHub用户名
EOF

# 3.2) 或导出到当前 shell（临时）
export GITLAB_ACCESS_TOKEN=glpat_xxx
export GITHUB_ACCESS_TOKEN=ghp_xxx
export GH_TOKEN=$GITHUB_ACCESS_TOKEN
export GITLAB_USERNAME=你的GitLab用户名
export GITHUB_OWNER=你的GitHub用户名

# 4) 运行
python3 index.py   # 程序会自动加载 .env
# 或使用 Import API（无本地克隆）
export USE_GITHUB_IMPORT=1 && python3 index.py
```

## 输出说明

```
📊 统计:
   代码迁移成功: 5/5
   CI/CD迁移成功: 3
   输出目录: ./migration-output

✨ 新建的 GitHub 仓库:
   https://github.com/wuuashen/project1
   https://github.com/wuuashen/project2
   ...
```

当存在失败时：

- 会在总结中标注“部分失败”或“全部失败”；
- 列出失败的仓库名称；
- 进程退出码为非 0，可通过 `$?` 检查。

## 常见问题（FAQ）

### Q1: 创建仓库报 “cannot create a repository for <A>”
- 说明当前 `gh` 登录主体无权在 `<A>` 名下创建仓库。请设置 `GITHUB_OWNER` 为你有权限的 owner，并确保 `GH_TOKEN` 与 `GITHUB_ACCESS_TOKEN` 一致。

### Q2: 推送失败，提示大文件超过 100MB（GH001）
- 输出会列出具体的文件路径。可选择：
  - 使用 Git LFS 管理大文件：`git lfs install && git lfs track <pattern>` 并重推；
  - 或清理历史移除大文件，再推送。

### Q3: 仓库名包含空格导致 URL 错误
- 工具会从 GitLab 仓库 URL 自动派生安全仓库名，并在 GitHub 上使用该安全名。

### Q4: 如何查看克隆与推送的详细日志？
- 工具已开启实时日志，包含执行的 git 命令（已脱敏）和完整输出，便于定位问题。

## 故障排除

### GitLab Token 权限不足
确保 GitLab Personal Access Token 具有以下权限：
- `api`
- `read_api` 
- `read_repository`

### GitHub Token 问题
```bash
# 重新登录 GitHub CLI
gh auth logout
gh auth login

# 检查权限
gh auth status
```

### 私有仓库访问失败
确保 GitLab Token 有访问私有仓库的权限。

### CI/CD 迁移失败
CI/CD 迁移失败不会影响代码迁移，代码仍会成功迁移到 GitHub。
可以手动检查 `./migration-output` 目录中的转换结果。

## 安全提示

- Token 仅在本地使用，不要上传到任何服务器
- 使用临时目录进行 git 操作，完成后自动清理
- 支持私有仓库迁移，保持原有可见性设置