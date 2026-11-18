# 兀渊学社 · Ecole π

独立的新 math blog，使用 Hugo 0.170.0 和 Bear Blog 主题。[旧博客](https://gausyu.top/MathBlog/) 保持独立，通过链接访问。

## 开始写作

需要 Python 3.13。首次使用时下载项目固定版本的官方 Hugo，并核对 SHA-256；程序只放在项目的 `.cache/` 中：

```sh
./blog setup
./blog new connected-schemes "Connected schemes and coproducts"
./blog preview
```

编辑 `content/posts/connected-schemes/index.md`。`new` 创建草稿，不自动填写发布日期；标题可用中文或英文。预览地址为 <http://127.0.0.1:1313/math-blog/>，包含草稿，仅在本机访问。

排版示例保存在 `tests/fixtures/layout-preview.md`，供检查正文、公式和脚注时使用。

`content/posts/introduction/index.md` 同时提供首篇文章与 About me 的正文。修改这一份即可同步两处；文章仍是草稿时，共用正文只在草稿预览中显示。

每篇文章围绕一个具体问题展开：交代背景与假设，用例子和论证解释关键一步，说明适用范围及实际使用的参考来源。模板内的注释只是提示，正文结构可自由安排。

正文使用 Markdown。行内公式写 `$X$`；独立公式的 `$$` 各占一行，并与相邻段落留空行：

```markdown
For a scheme $X$, consider

$$
\operatorname{Hom}(X,Y_1\sqcup Y_2).
$$

Continue the argument here.[^reference]

[^reference]: Give the source and the relevant section or result.
```

脚注使用 `[^name]`，代码使用带语言名的 fenced code block。图片和其他附件放在文章同一目录，可用 `![说明](figure.png)` 引用；每个文章目录只放一份正文 `index.md`。

## 在本地发布

写完后明确指定发布日期：

```sh
./blog publish connected-schemes --date 2026-11-17
./blog check
./blog build
./blog serve
```

`publish` 将该文标记为正式文章，填写 Asia/Shanghai 时区的日期，保留正文和附件。它只修改本地文件，不提交、不推送，也不部署。`check` 检查文章与写作命令；`build` 生成不含草稿的 `public/`；`serve` 在 <http://127.0.0.1:1314/math-blog/> 提供正式构建，运行前需先完成 `build`。

`connected-schemes` 是稳定的文章标识。正式 URL 为 `/math-blog/posts/connected-schemes/`，不包含日期；首次上线后保持该标识和目录名不变。更改显示标题不会改变 URL。只有有意标示修订日期时，才手动填写或修改 `lastmod`；文件修改时间和 Git 时间都不会自动成为发布日期或修订日期。

使用 `./blog --help` 查看命令；预览端口可通过 `./blog preview --port 1315` 调整。正式上线前需确认站点地址和部署目标；本地写作命令不会执行远程操作。

## 网站部署

新站源码使用独立的 GitHub 仓库。`hugo.toml` 暂按 `https://gausyu.top/math-blog/` 配置；仓库名称或发布地址变化时同步调整 `baseURL`。

首次部署，在新仓库的 Settings → Pages 中选择 GitHub Actions。推送 `main` 或打开 pull request 会运行 **Check**，执行检查和正式构建，并保存可下载的预览产物。上线时，在 Actions 中手动运行 **Publish website**；该流程通过检查后部署到 GitHub Pages。普通推送不会自动上线。

主题源自 MIT 许可的 Hugo Bear Blog，上游版本记录在 `themes/bear/UPSTREAM.json`，本地版式覆盖位于 `layouts/` 和 `assets/css/journal.css`。公式在构建时渲染，所需字体与 CSS 随站点提供。
