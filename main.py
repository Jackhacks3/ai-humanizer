import re
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
import fitz  # PyMuPDF
from typing import Optional

app = FastAPI(title="AI Text Humanizer")

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
    doc = fitz.open(stream=content, filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text


@app.get("/", response_class=HTMLResponse)
async def root():
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Text Humanizer</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
            min-height: 100vh;
            color: #e4e4e4;
        }

        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 40px 20px;
        }

        header {
            text-align: center;
            margin-bottom: 40px;
        }

        h1 {
            font-size: 2.5rem;
            background: linear-gradient(90deg, #e94560, #0f3460);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 10px;
        }

        .subtitle {
            color: #888;
            font-size: 1.1rem;
        }

        .main-content {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 30px;
        }

        @media (max-width: 900px) {
            .main-content {
                grid-template-columns: 1fr;
            }
        }

        .panel {
            background: rgba(255, 255, 255, 0.05);
            border-radius: 16px;
            padding: 24px;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.1);
        }

        .panel h2 {
            font-size: 1.2rem;
            margin-bottom: 16px;
            color: #e94560;
        }

        textarea {
            width: 100%;
            height: 300px;
            background: rgba(0, 0, 0, 0.3);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 8px;
            padding: 16px;
            color: #e4e4e4;
            font-size: 14px;
            line-height: 1.6;
            resize: vertical;
            font-family: inherit;
        }

        textarea:focus {
            outline: none;
            border-color: #e94560;
        }

        .upload-zone {
            border: 2px dashed rgba(233, 69, 96, 0.5);
            border-radius: 8px;
            padding: 30px;
            text-align: center;
            margin-bottom: 16px;
            cursor: pointer;
            transition: all 0.3s ease;
        }

        .upload-zone:hover {
            border-color: #e94560;
            background: rgba(233, 69, 96, 0.1);
        }

        .upload-zone.dragover {
            border-color: #e94560;
            background: rgba(233, 69, 96, 0.2);
        }

        .upload-icon {
            font-size: 48px;
            margin-bottom: 10px;
        }

        input[type="file"] {
            display: none;
        }

        .btn {
            background: linear-gradient(90deg, #e94560, #0f3460);
            color: white;
            border: none;
            padding: 14px 28px;
            border-radius: 8px;
            font-size: 16px;
            cursor: pointer;
            width: 100%;
            margin-top: 16px;
            transition: transform 0.2s, box-shadow 0.2s;
            font-weight: 600;
        }

        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 30px rgba(233, 69, 96, 0.3);
        }

        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }

        .stats {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 12px;
            margin-top: 16px;
        }

        .stat {
            background: rgba(0, 0, 0, 0.3);
            padding: 12px;
            border-radius: 8px;
            text-align: center;
        }

        .stat-value {
            font-size: 1.5rem;
            font-weight: bold;
            color: #e94560;
        }

        .stat-label {
            font-size: 0.75rem;
            color: #888;
            text-transform: uppercase;
        }

        .changes-list {
            margin-top: 16px;
            background: rgba(0, 0, 0, 0.2);
            border-radius: 8px;
            padding: 16px;
            max-height: 150px;
            overflow-y: auto;
        }

        .changes-list h3 {
            font-size: 0.9rem;
            margin-bottom: 10px;
            color: #e94560;
        }

        .changes-list ul {
            list-style: none;
        }

        .changes-list li {
            padding: 4px 0;
            font-size: 0.85rem;
            color: #aaa;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        }

        .changes-list li:last-child {
            border-bottom: none;
        }

        .copy-btn {
            background: rgba(233, 69, 96, 0.2);
            color: #e94560;
            border: 1px solid #e94560;
            padding: 8px 16px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
            margin-top: 12px;
            transition: all 0.2s;
        }

        .copy-btn:hover {
            background: #e94560;
            color: white;
        }

        .loading {
            display: none;
            text-align: center;
            padding: 20px;
        }

        .spinner {
            width: 40px;
            height: 40px;
            border: 3px solid rgba(233, 69, 96, 0.3);
            border-top-color: #e94560;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 10px;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        .ai-tells {
            margin-top: 40px;
            padding: 24px;
            background: rgba(255, 255, 255, 0.03);
            border-radius: 16px;
        }

        .ai-tells h3 {
            color: #e94560;
            margin-bottom: 16px;
        }

        .tells-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 16px;
        }

        .tell-item {
            background: rgba(0, 0, 0, 0.2);
            padding: 16px;
            border-radius: 8px;
        }

        .tell-item strong {
            color: #e94560;
        }

        .tell-item code {
            background: rgba(233, 69, 96, 0.2);
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 0.85rem;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>AI Text Humanizer</h1>
            <p class="subtitle">Remove AI writing patterns from Claude, GPT, and other models</p>
        </header>

        <div class="main-content">
            <div class="panel">
                <h2>Input</h2>

                <div class="upload-zone" id="dropZone">
                    <div class="upload-icon">📄</div>
                    <p>Drop PDF here or click to upload</p>
                    <p style="font-size: 12px; color: #666; margin-top: 8px;">or paste text below</p>
                </div>
                <input type="file" id="fileInput" accept=".pdf,.txt">

                <textarea id="inputText" placeholder="Paste your AI-generated text here...

Example AI patterns that will be removed:
- **Bold text** like this
- Double dashes -- like this
- # Markdown headers
- Numbered lists (1. 2. 3.)
- Em dashes — like this
- 'Let me explain...', 'Here's...', 'Certainly!'"></textarea>

                <button class="btn" id="humanizeBtn">Humanize Text</button>
            </div>

            <div class="panel">
                <h2>Output</h2>

                <div class="loading" id="loading">
                    <div class="spinner"></div>
                    <p>Processing...</p>
                </div>

                <textarea id="outputText" readonly placeholder="Humanized text will appear here..."></textarea>

                <button class="copy-btn" id="copyBtn">Copy to Clipboard</button>

                <div class="stats" id="stats" style="display: none;">
                    <div class="stat">
                        <div class="stat-value" id="originalLen">0</div>
                        <div class="stat-label">Original</div>
                    </div>
                    <div class="stat">
                        <div class="stat-value" id="humanizedLen">0</div>
                        <div class="stat-label">Cleaned</div>
                    </div>
                    <div class="stat">
                        <div class="stat-value" id="reduction">0</div>
                        <div class="stat-label">Removed</div>
                    </div>
                </div>

                <div class="changes-list" id="changesList" style="display: none;">
                    <h3>Changes Made</h3>
                    <ul id="changesUl"></ul>
                </div>
            </div>
        </div>

        <div class="ai-tells">
            <h3>AI Writing Patterns Detected & Removed</h3>
            <div class="tells-grid">
                <div class="tell-item">
                    <strong>Claude</strong>
                    <p><code>**bold text**</code> overuse, structured lists, "Let me..."</p>
                </div>
                <div class="tell-item">
                    <strong>GPT</strong>
                    <p><code>--</code> double dashes, em dashes <code>—</code>, "Certainly!"</p>
                </div>
                <div class="tell-item">
                    <strong>Markdown</strong>
                    <p><code># Headers</code>, <code>`code`</code>, <code>[links](url)</code></p>
                </div>
                <div class="tell-item">
                    <strong>Formatting</strong>
                    <p>Bullet points, numbered lists, blockquotes <code>></code></p>
                </div>
            </div>
        </div>
    </div>

    <script>
        const dropZone = document.getElementById('dropZone');
        const fileInput = document.getElementById('fileInput');
        const inputText = document.getElementById('inputText');
        const outputText = document.getElementById('outputText');
        const humanizeBtn = document.getElementById('humanizeBtn');
        const copyBtn = document.getElementById('copyBtn');
        const loading = document.getElementById('loading');
        const stats = document.getElementById('stats');
        const changesList = document.getElementById('changesList');

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

                loading.style.display = 'block';
                outputText.style.display = 'none';

                try {
                    const response = await fetch('/upload-pdf', {
                        method: 'POST',
                        body: formData
                    });
                    const data = await response.json();
                    inputText.value = data.text;
                } catch (error) {
                    alert('Error processing PDF: ' + error.message);
                } finally {
                    loading.style.display = 'none';
                    outputText.style.display = 'block';
                }
            } else if (file.type === 'text/plain') {
                const reader = new FileReader();
                reader.onload = (e) => {
                    inputText.value = e.target.result;
                };
                reader.readAsText(file);
            }
        }

        humanizeBtn.addEventListener('click', async () => {
            const text = inputText.value.trim();
            if (!text) {
                alert('Please enter some text to humanize');
                return;
            }

            humanizeBtn.disabled = true;
            loading.style.display = 'block';
            outputText.style.display = 'none';

            try {
                const response = await fetch('/humanize', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: `text=${encodeURIComponent(text)}`
                });
                const data = await response.json();

                outputText.value = data.humanized;

                // Update stats
                document.getElementById('originalLen').textContent = data.original_length;
                document.getElementById('humanizedLen').textContent = data.humanized_length;
                document.getElementById('reduction').textContent = data.reduction;
                stats.style.display = 'grid';

                // Update changes list
                const changesUl = document.getElementById('changesUl');
                changesUl.innerHTML = '';
                if (data.changes.length > 0) {
                    data.changes.forEach(change => {
                        const li = document.createElement('li');
                        li.textContent = '✓ ' + change;
                        changesUl.appendChild(li);
                    });
                    changesList.style.display = 'block';
                } else {
                    const li = document.createElement('li');
                    li.textContent = 'No AI patterns detected';
                    changesUl.appendChild(li);
                    changesList.style.display = 'block';
                }

            } catch (error) {
                alert('Error: ' + error.message);
            } finally {
                humanizeBtn.disabled = false;
                loading.style.display = 'none';
                outputText.style.display = 'block';
            }
        });

        copyBtn.addEventListener('click', () => {
            outputText.select();
            document.execCommand('copy');
            copyBtn.textContent = 'Copied!';
            setTimeout(() => {
                copyBtn.textContent = 'Copy to Clipboard';
            }, 2000);
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
