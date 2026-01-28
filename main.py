import re
import io
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
import pdfplumber
from typing import Optional

app = FastAPI(title="ByeDash")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def humanize_text(text: str) -> dict:
    """Remove AI writing tells from text."""
    original = text
    changes = []

    # 1. Remove markdown bold (**text** or __text__)
    bold_pattern = r'\*\*([^*]+)\*\*|__([^_]+)__'
    bold_matches = re.findall(bold_pattern, text)
    if bold_matches:
        changes.append(f"Removed {len(bold_matches)} bold formatting instances")
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'__([^_]+)__', r'\1', text)

    # 2. Remove markdown italic (*text* or _text_) - careful not to break contractions
    italic_pattern = r'(?<![a-zA-Z])\*([^*\n]+)\*(?![a-zA-Z])|(?<![a-zA-Z])_([^_\n]+)_(?![a-zA-Z])'
    italic_matches = re.findall(italic_pattern, text)
    if italic_matches:
        changes.append(f"Removed {len(italic_matches)} italic formatting instances")
    text = re.sub(r'(?<![a-zA-Z])\*([^*\n]+)\*(?![a-zA-Z])', r'\1', text)
    text = re.sub(r'(?<![a-zA-Z])_([^_\n]+)_(?![a-zA-Z])', r'\1', text)

    # 3. Replace em dashes with regular dashes or commas
    em_dash_count = text.count('—') + text.count('–') + len(re.findall(r'(?<!\-)\-\-(?!\-)', text))
    if em_dash_count:
        changes.append(f"Replaced {em_dash_count} em dashes/double dashes")
    text = text.replace('—', ', ')  # em dash
    text = text.replace('–', '-')   # en dash
    text = re.sub(r'(?<!\-)\-\-(?!\-)', ', ', text)  # double dash

    # 4. Remove markdown headers (# ## ### etc)
    header_matches = re.findall(r'^#{1,6}\s+', text, re.MULTILINE)
    if header_matches:
        changes.append(f"Removed {len(header_matches)} markdown headers")
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)

    # 5. Convert markdown bullet points to plain text
    bullet_matches = re.findall(r'^[\s]*[-*+]\s+', text, re.MULTILINE)
    if bullet_matches:
        changes.append(f"Converted {len(bullet_matches)} bullet points")
    text = re.sub(r'^[\s]*[-*+]\s+', '- ', text, flags=re.MULTILINE)

    # 6. Remove numbered list formatting (1. 2. etc) - make them inline
    numbered_matches = re.findall(r'^\s*\d+\.\s+', text, re.MULTILINE)
    if numbered_matches:
        changes.append(f"Simplified {len(numbered_matches)} numbered items")
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)

    # 7. Remove code blocks (```language ... ```)
    code_block_matches = re.findall(r'```[\s\S]*?```', text)
    if code_block_matches:
        changes.append(f"Removed {len(code_block_matches)} code block markers")
    text = re.sub(r'```[a-z]*\n?', '', text)
    text = re.sub(r'```', '', text)

    # 8. Remove inline code (`code`)
    inline_code_matches = re.findall(r'`[^`]+`', text)
    if inline_code_matches:
        changes.append(f"Removed {len(inline_code_matches)} inline code markers")
    text = re.sub(r'`([^`]+)`', r'\1', text)

    # 9. Remove AI-typical sentence starters
    ai_starters = [
        (r"(?i)^Let me ", ""),
        (r"(?i)^I'll ", ""),
        (r"(?i)^Here's ", ""),
        (r"(?i)^Here is ", ""),
        (r"(?i)^Certainly[,!]?\s*", ""),
        (r"(?i)^Of course[,!]?\s*", ""),
        (r"(?i)^Absolutely[,!]?\s*", ""),
        (r"(?i)^Great question[,!]?\s*", ""),
        (r"(?i)^That's a great ", "A "),
        (r"(?i)^I'd be happy to ", ""),
        (r"(?i)^I would be happy to ", ""),
    ]
    starter_count = 0
    for pattern, replacement in ai_starters:
        matches = re.findall(pattern, text, re.MULTILINE)
        starter_count += len(matches)
        text = re.sub(pattern, replacement, text, flags=re.MULTILINE)
    if starter_count:
        changes.append(f"Removed {starter_count} AI-typical sentence starters")

    # 10. Remove excessive exclamation marks (more than 1)
    exclaim_matches = re.findall(r'!{2,}', text)
    if exclaim_matches:
        changes.append(f"Normalized {len(exclaim_matches)} excessive exclamation marks")
    text = re.sub(r'!{2,}', '!', text)

    # 11. Remove trailing colons before lists (AI pattern)
    colon_matches = re.findall(r':\s*\n\s*[-*\d]', text)
    if colon_matches:
        changes.append(f"Adjusted {len(colon_matches)} colon-before-list patterns")
    text = re.sub(r':\s*\n(\s*[-*\d])', r'.\n\1', text)

    # 12. Clean up multiple newlines
    text = re.sub(r'\n{3,}', '\n\n', text)

    # 13. Clean up multiple spaces
    text = re.sub(r' {2,}', ' ', text)

    # 14. Remove links in markdown format [text](url)
    link_matches = re.findall(r'\[([^\]]+)\]\([^)]+\)', text)
    if link_matches:
        changes.append(f"Simplified {len(link_matches)} markdown links")
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)

    # 15. Remove blockquotes
    quote_matches = re.findall(r'^>\s*', text, re.MULTILINE)
    if quote_matches:
        changes.append(f"Removed {len(quote_matches)} blockquote markers")
    text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)

    # 16. Remove horizontal rules
    hr_matches = re.findall(r'^[-*_]{3,}\s*$', text, re.MULTILINE)
    if hr_matches:
        changes.append(f"Removed {len(hr_matches)} horizontal rules")
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)

    # Final trim
    text = text.strip()

    return {
        "original": original,
        "humanized": text,
        "changes": changes,
        "original_length": len(original),
        "humanized_length": len(text),
        "reduction": len(original) - len(text)
    }


async def extract_pdf_text(file: UploadFile) -> str:
    """Extract text from uploaded PDF."""
    content = await file.read()
    text = ""
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text


@app.get("/", response_class=HTMLResponse)
async def root():
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ByeDash</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #0a0a0a;
            --bg-secondary: #111111;
            --bg-tertiary: #1a1a1a;
            --border: #262626;
            --border-hover: #404040;
            --text-primary: #fafafa;
            --text-secondary: #a1a1a1;
            --text-muted: #525252;
            --accent: #22c55e;
            --accent-dim: rgba(34, 197, 94, 0.1);
            --accent-border: rgba(34, 197, 94, 0.3);
            --danger: #ef4444;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        html {
            font-size: 15px;
        }

        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            line-height: 1.5;
            -webkit-font-smoothing: antialiased;
        }

        .app {
            max-width: 1400px;
            margin: 0 auto;
            padding: 0 24px;
        }

        /* Navigation */
        nav {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 20px 0;
            border-bottom: 1px solid var(--border);
        }

        .logo {
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .logo-mark {
            width: 32px;
            height: 32px;
            background: var(--accent);
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 600;
            font-size: 14px;
            color: var(--bg-primary);
        }

        .logo-text {
            font-size: 18px;
            font-weight: 600;
            letter-spacing: -0.5px;
        }

        .nav-links {
            display: flex;
            gap: 32px;
        }

        .nav-links a {
            color: var(--text-secondary);
            text-decoration: none;
            font-size: 14px;
            font-weight: 400;
            transition: color 0.15s;
        }

        .nav-links a:hover {
            color: var(--text-primary);
        }

        /* Hero */
        .hero {
            padding: 80px 0 60px;
            text-align: center;
            max-width: 680px;
            margin: 0 auto;
        }

        .badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 6px 12px;
            background: var(--accent-dim);
            border: 1px solid var(--accent-border);
            border-radius: 100px;
            font-size: 12px;
            font-weight: 500;
            color: var(--accent);
            margin-bottom: 24px;
        }

        .badge-dot {
            width: 6px;
            height: 6px;
            background: var(--accent);
            border-radius: 50%;
            animation: pulse 2s infinite;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        h1 {
            font-size: 48px;
            font-weight: 600;
            letter-spacing: -1.5px;
            line-height: 1.1;
            margin-bottom: 16px;
        }

        .hero p {
            font-size: 17px;
            color: var(--text-secondary);
            line-height: 1.6;
        }

        /* Main Editor */
        .editor-container {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1px;
            background: var(--border);
            border: 1px solid var(--border);
            border-radius: 12px;
            overflow: hidden;
            margin-bottom: 24px;
        }

        @media (max-width: 900px) {
            .editor-container {
                grid-template-columns: 1fr;
            }
        }

        .editor-panel {
            background: var(--bg-secondary);
            display: flex;
            flex-direction: column;
        }

        .panel-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 12px 16px;
            border-bottom: 1px solid var(--border);
            background: var(--bg-tertiary);
        }

        .panel-title {
            font-size: 12px;
            font-weight: 500;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .panel-actions {
            display: flex;
            gap: 8px;
        }

        .icon-btn {
            width: 28px;
            height: 28px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: transparent;
            border: 1px solid var(--border);
            border-radius: 6px;
            color: var(--text-secondary);
            cursor: pointer;
            transition: all 0.15s;
        }

        .icon-btn:hover {
            background: var(--bg-tertiary);
            border-color: var(--border-hover);
            color: var(--text-primary);
        }

        .icon-btn svg {
            width: 14px;
            height: 14px;
        }

        .editor-area {
            flex: 1;
            position: relative;
        }

        textarea {
            width: 100%;
            height: 400px;
            background: transparent;
            border: none;
            padding: 20px;
            color: var(--text-primary);
            font-family: 'JetBrains Mono', monospace;
            font-size: 13px;
            line-height: 1.7;
            resize: none;
        }

        textarea:focus {
            outline: none;
        }

        textarea::placeholder {
            color: var(--text-muted);
        }

        .output-area {
            position: relative;
        }

        #outputText {
            background: var(--bg-secondary);
        }

        /* Upload Zone */
        .upload-zone {
            margin: 16px;
            padding: 32px;
            border: 1px dashed var(--border);
            border-radius: 8px;
            text-align: center;
            cursor: pointer;
            transition: all 0.2s;
        }

        .upload-zone:hover {
            border-color: var(--border-hover);
            background: var(--bg-tertiary);
        }

        .upload-zone.dragover {
            border-color: var(--accent);
            background: var(--accent-dim);
        }

        .upload-icon {
            width: 40px;
            height: 40px;
            margin: 0 auto 12px;
            border: 1px solid var(--border);
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            color: var(--text-secondary);
        }

        .upload-text {
            font-size: 13px;
            color: var(--text-secondary);
        }

        .upload-text span {
            color: var(--accent);
            font-weight: 500;
        }

        .upload-hint {
            font-size: 12px;
            color: var(--text-muted);
            margin-top: 4px;
        }

        input[type="file"] {
            display: none;
        }

        /* Action Bar */
        .action-bar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 16px 20px;
            background: var(--bg-tertiary);
            border-top: 1px solid var(--border);
        }

        .char-count {
            font-family: 'JetBrains Mono', monospace;
            font-size: 12px;
            color: var(--text-muted);
        }

        .btn-primary {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 10px 20px;
            background: var(--text-primary);
            color: var(--bg-primary);
            border: none;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.15s;
        }

        .btn-primary:hover {
            background: #e5e5e5;
            transform: translateY(-1px);
        }

        .btn-primary:active {
            transform: translateY(0);
        }

        .btn-primary:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }

        .btn-primary svg {
            width: 16px;
            height: 16px;
        }

        .btn-secondary {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 8px 14px;
            background: transparent;
            color: var(--text-secondary);
            border: 1px solid var(--border);
            border-radius: 6px;
            font-size: 12px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.15s;
        }

        .btn-secondary:hover {
            background: var(--bg-tertiary);
            border-color: var(--border-hover);
            color: var(--text-primary);
        }

        .btn-secondary.success {
            color: var(--accent);
            border-color: var(--accent-border);
            background: var(--accent-dim);
        }

        /* Stats Bar */
        .stats-bar {
            display: none;
            grid-template-columns: repeat(4, 1fr);
            gap: 1px;
            background: var(--border);
            border: 1px solid var(--border);
            border-radius: 8px;
            overflow: hidden;
            margin-bottom: 24px;
        }

        .stats-bar.visible {
            display: grid;
        }

        .stat-item {
            background: var(--bg-secondary);
            padding: 16px 20px;
            text-align: center;
        }

        .stat-value {
            font-family: 'JetBrains Mono', monospace;
            font-size: 24px;
            font-weight: 500;
            color: var(--text-primary);
            margin-bottom: 4px;
        }

        .stat-value.positive {
            color: var(--accent);
        }

        .stat-value.negative {
            color: var(--danger);
        }

        .stat-label {
            font-size: 11px;
            font-weight: 500;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        /* Changes Log */
        .changes-log {
            display: none;
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 8px;
            overflow: hidden;
            margin-bottom: 24px;
        }

        .changes-log.visible {
            display: block;
        }

        .log-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 12px 16px;
            background: var(--bg-tertiary);
            border-bottom: 1px solid var(--border);
        }

        .log-title {
            font-size: 12px;
            font-weight: 500;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .log-count {
            font-family: 'JetBrains Mono', monospace;
            font-size: 11px;
            padding: 2px 8px;
            background: var(--accent-dim);
            color: var(--accent);
            border-radius: 100px;
        }

        .log-list {
            padding: 12px 16px;
            max-height: 160px;
            overflow-y: auto;
        }

        .log-item {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 8px 0;
            font-size: 13px;
            color: var(--text-secondary);
            border-bottom: 1px solid var(--border);
        }

        .log-item:last-child {
            border-bottom: none;
        }

        .log-icon {
            width: 18px;
            height: 18px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: var(--accent-dim);
            border-radius: 50%;
            color: var(--accent);
            flex-shrink: 0;
        }

        .log-icon svg {
            width: 10px;
            height: 10px;
        }

        /* Features Grid */
        .features {
            padding: 60px 0;
            border-top: 1px solid var(--border);
        }

        .features-header {
            text-align: center;
            margin-bottom: 40px;
        }

        .features-header h2 {
            font-size: 14px;
            font-weight: 500;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 8px;
        }

        .features-header p {
            font-size: 24px;
            font-weight: 500;
            letter-spacing: -0.5px;
        }

        .features-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 1px;
            background: var(--border);
            border: 1px solid var(--border);
            border-radius: 12px;
            overflow: hidden;
        }

        @media (max-width: 900px) {
            .features-grid {
                grid-template-columns: repeat(2, 1fr);
            }
        }

        @media (max-width: 500px) {
            .features-grid {
                grid-template-columns: 1fr;
            }
        }

        .feature-card {
            background: var(--bg-secondary);
            padding: 24px;
        }

        .feature-icon {
            width: 36px;
            height: 36px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: var(--bg-tertiary);
            border: 1px solid var(--border);
            border-radius: 8px;
            margin-bottom: 16px;
            font-size: 16px;
        }

        .feature-card h3 {
            font-size: 14px;
            font-weight: 500;
            margin-bottom: 6px;
        }

        .feature-card p {
            font-size: 13px;
            color: var(--text-secondary);
            line-height: 1.5;
        }

        .feature-card code {
            font-family: 'JetBrains Mono', monospace;
            font-size: 11px;
            padding: 2px 6px;
            background: var(--bg-tertiary);
            border-radius: 4px;
            color: var(--text-muted);
        }

        /* Footer */
        footer {
            padding: 24px 0;
            border-top: 1px solid var(--border);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .footer-text {
            font-size: 13px;
            color: var(--text-muted);
        }

        .footer-links {
            display: flex;
            gap: 24px;
        }

        .footer-links a {
            font-size: 13px;
            color: var(--text-secondary);
            text-decoration: none;
            transition: color 0.15s;
        }

        .footer-links a:hover {
            color: var(--text-primary);
        }

        /* Loading State */
        .loading-overlay {
            position: absolute;
            inset: 0;
            background: rgba(10, 10, 10, 0.9);
            display: none;
            align-items: center;
            justify-content: center;
            flex-direction: column;
            gap: 12px;
        }

        .loading-overlay.visible {
            display: flex;
        }

        .loader {
            width: 24px;
            height: 24px;
            border: 2px solid var(--border);
            border-top-color: var(--accent);
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        .loading-text {
            font-size: 12px;
            color: var(--text-muted);
        }

        /* Keyboard shortcut hint */
        .shortcut {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            margin-left: 8px;
        }

        .key {
            font-family: 'JetBrains Mono', monospace;
            font-size: 10px;
            padding: 2px 5px;
            background: var(--bg-tertiary);
            border: 1px solid var(--border);
            border-radius: 4px;
            color: var(--text-muted);
        }
    </style>
</head>
<body>
    <div class="app">
        <nav>
            <div class="logo">
                <div class="logo-mark">B</div>
                <span class="logo-text">ByeDash</span>
            </div>
            <div class="nav-links">
                <a href="#features">Features</a>
                <a href="https://github.com/Jackhacks3/ai-humanizer" target="_blank">GitHub</a>
            </div>
        </nav>

        <section class="hero">
            <div class="badge">
                <span class="badge-dot"></span>
                Strip AI fingerprints instantly
            </div>
            <h1>Make AI text undetectable</h1>
            <p>Remove formatting patterns, stylistic tells, and structural markers that flag content as AI-generated. Works with Claude, GPT, Gemini, and more.</p>
        </section>

        <div class="editor-container">
            <div class="editor-panel">
                <div class="panel-header">
                    <span class="panel-title">Input</span>
                    <div class="panel-actions">
                        <button class="icon-btn" id="clearBtn" title="Clear">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <path d="M18 6L6 18M6 6l12 12"/>
                            </svg>
                        </button>
                    </div>
                </div>
                <div class="upload-zone" id="dropZone">
                    <div class="upload-icon">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                            <polyline points="17 8 12 3 7 8"/>
                            <line x1="12" y1="3" x2="12" y2="15"/>
                        </svg>
                    </div>
                    <p class="upload-text"><span>Click to upload</span> or drag and drop</p>
                    <p class="upload-hint">PDF or TXT files supported</p>
                </div>
                <input type="file" id="fileInput" accept=".pdf,.txt">
                <div class="editor-area">
                    <textarea id="inputText" placeholder="Paste your AI-generated text here..."></textarea>
                </div>
                <div class="action-bar">
                    <span class="char-count"><span id="inputCount">0</span> characters</span>
                    <button class="btn-primary" id="processBtn">
                        Process
                        <span class="shortcut">
                            <span class="key">Ctrl</span>
                            <span class="key">Enter</span>
                        </span>
                    </button>
                </div>
            </div>
            <div class="editor-panel">
                <div class="panel-header">
                    <span class="panel-title">Output</span>
                    <div class="panel-actions">
                        <button class="btn-secondary" id="copyBtn">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                            </svg>
                            Copy
                        </button>
                    </div>
                </div>
                <div class="editor-area output-area">
                    <textarea id="outputText" readonly placeholder="Processed text will appear here..."></textarea>
                    <div class="loading-overlay" id="loading">
                        <div class="loader"></div>
                        <span class="loading-text">Processing...</span>
                    </div>
                </div>
                <div class="action-bar">
                    <span class="char-count"><span id="outputCount">0</span> characters</span>
                    <span class="char-count" id="reductionText" style="color: var(--accent);"></span>
                </div>
            </div>
        </div>

        <div class="stats-bar" id="statsBar">
            <div class="stat-item">
                <div class="stat-value" id="statOriginal">0</div>
                <div class="stat-label">Original</div>
            </div>
            <div class="stat-item">
                <div class="stat-value" id="statProcessed">0</div>
                <div class="stat-label">Processed</div>
            </div>
            <div class="stat-item">
                <div class="stat-value positive" id="statRemoved">0</div>
                <div class="stat-label">Removed</div>
            </div>
            <div class="stat-item">
                <div class="stat-value" id="statChanges">0</div>
                <div class="stat-label">Changes</div>
            </div>
        </div>

        <div class="changes-log" id="changesLog">
            <div class="log-header">
                <span class="log-title">Changes Applied</span>
                <span class="log-count" id="logCount">0</span>
            </div>
            <div class="log-list" id="logList"></div>
        </div>

        <section class="features" id="features">
            <div class="features-header">
                <h2>What gets removed</h2>
                <p>AI fingerprints we detect and strip</p>
            </div>
            <div class="features-grid">
                <div class="feature-card">
                    <div class="feature-icon">C</div>
                    <h3>Claude Patterns</h3>
                    <p>Excessive <code>**bold**</code> formatting, structured responses, "Let me explain..."</p>
                </div>
                <div class="feature-card">
                    <div class="feature-icon">G</div>
                    <h3>GPT Patterns</h3>
                    <p>Double dashes <code>--</code>, em dashes, "Certainly!", "Absolutely!"</p>
                </div>
                <div class="feature-card">
                    <div class="feature-icon">#</div>
                    <h3>Markdown</h3>
                    <p>Headers, code blocks, <code>[links](url)</code>, blockquotes, horizontal rules</p>
                </div>
                <div class="feature-card">
                    <div class="feature-icon">1.</div>
                    <h3>Structure</h3>
                    <p>Numbered lists, bullet points, excessive whitespace, colon-before-list patterns</p>
                </div>
            </div>
        </section>

        <footer>
            <span class="footer-text">Built for humans, by humans</span>
            <div class="footer-links">
                <a href="https://github.com/Jackhacks3/ai-humanizer" target="_blank">Source</a>
            </div>
        </footer>
    </div>

    <script>
        const dropZone = document.getElementById('dropZone');
        const fileInput = document.getElementById('fileInput');
        const inputText = document.getElementById('inputText');
        const outputText = document.getElementById('outputText');
        const processBtn = document.getElementById('processBtn');
        const copyBtn = document.getElementById('copyBtn');
        const clearBtn = document.getElementById('clearBtn');
        const loading = document.getElementById('loading');
        const statsBar = document.getElementById('statsBar');
        const changesLog = document.getElementById('changesLog');
        const inputCount = document.getElementById('inputCount');
        const outputCount = document.getElementById('outputCount');
        const reductionText = document.getElementById('reductionText');

        // Character count
        inputText.addEventListener('input', () => {
            inputCount.textContent = inputText.value.length.toLocaleString();
        });

        // Clear button
        clearBtn.addEventListener('click', () => {
            inputText.value = '';
            inputCount.textContent = '0';
        });

        // Drag and drop
        dropZone.addEventListener('click', () => fileInput.click());

        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('dragover');
        });

        dropZone.addEventListener('dragleave', () => {
            dropZone.classList.remove('dragover');
        });

        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('dragover');
            const file = e.dataTransfer.files[0];
            if (file) handleFile(file);
        });

        fileInput.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (file) handleFile(file);
        });

        async function handleFile(file) {
            if (file.type === 'application/pdf') {
                const formData = new FormData();
                formData.append('file', file);
                loading.classList.add('visible');

                try {
                    const response = await fetch('/upload-pdf', {
                        method: 'POST',
                        body: formData
                    });
                    const data = await response.json();
                    inputText.value = data.text;
                    inputCount.textContent = data.text.length.toLocaleString();
                } catch (error) {
                    console.error('Error processing PDF:', error);
                } finally {
                    loading.classList.remove('visible');
                }
            } else if (file.type === 'text/plain') {
                const reader = new FileReader();
                reader.onload = (e) => {
                    inputText.value = e.target.result;
                    inputCount.textContent = e.target.result.length.toLocaleString();
                };
                reader.readAsText(file);
            }
        }

        // Keyboard shortcut
        document.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                e.preventDefault();
                processBtn.click();
            }
        });

        // Process button
        processBtn.addEventListener('click', async () => {
            const text = inputText.value.trim();
            if (!text) return;

            processBtn.disabled = true;
            loading.classList.add('visible');

            try {
                const response = await fetch('/humanize', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: `text=${encodeURIComponent(text)}`
                });
                const data = await response.json();

                outputText.value = data.humanized;
                outputCount.textContent = data.humanized_length.toLocaleString();

                // Stats
                document.getElementById('statOriginal').textContent = data.original_length.toLocaleString();
                document.getElementById('statProcessed').textContent = data.humanized_length.toLocaleString();
                document.getElementById('statRemoved').textContent = data.reduction.toLocaleString();
                document.getElementById('statChanges').textContent = data.changes.length;
                statsBar.classList.add('visible');

                if (data.reduction > 0) {
                    reductionText.textContent = `-${data.reduction} chars removed`;
                } else {
                    reductionText.textContent = '';
                }

                // Changes log
                const logList = document.getElementById('logList');
                logList.innerHTML = '';
                document.getElementById('logCount').textContent = data.changes.length;

                if (data.changes.length > 0) {
                    data.changes.forEach(change => {
                        const item = document.createElement('div');
                        item.className = 'log-item';
                        item.innerHTML = `
                            <span class="log-icon">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                                    <polyline points="20 6 9 17 4 12"/>
                                </svg>
                            </span>
                            <span>${change}</span>
                        `;
                        logList.appendChild(item);
                    });
                    changesLog.classList.add('visible');
                } else {
                    const item = document.createElement('div');
                    item.className = 'log-item';
                    item.innerHTML = '<span>No AI patterns detected</span>';
                    logList.appendChild(item);
                    changesLog.classList.add('visible');
                }

            } catch (error) {
                console.error('Error:', error);
            } finally {
                processBtn.disabled = false;
                loading.classList.remove('visible');
            }
        });

        // Copy button
        copyBtn.addEventListener('click', async () => {
            try {
                await navigator.clipboard.writeText(outputText.value);
                copyBtn.classList.add('success');
                copyBtn.innerHTML = `
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="20 6 9 17 4 12"/>
                    </svg>
                    Copied
                `;
                setTimeout(() => {
                    copyBtn.classList.remove('success');
                    copyBtn.innerHTML = `
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                        </svg>
                        Copy
                    `;
                }, 2000);
            } catch (err) {
                outputText.select();
                document.execCommand('copy');
            }
        });
    </script>
</body>
</html>"""


@app.post("/humanize")
async def humanize(text: str = Form(...)):
    """Humanize AI-generated text."""
    result = humanize_text(text)
    return JSONResponse(result)


@app.post("/upload-pdf")
async def upload_pdf(file: UploadFile = File(...)):
    """Extract text from uploaded PDF."""
    text = await extract_pdf_text(file)
    return {"text": text}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
