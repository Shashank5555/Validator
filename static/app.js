const INITIAL_EDITOR_VALUE = '';
const DEFAULT_THEME = 'dark';
const DEFAULT_FONT_SIZE = 13;
const MIN_FONT_SIZE = 11;
const MAX_FONT_SIZE = 20;
const MAX_FORMAT_ITERATIONS = 2;

const editor = CodeMirror(document.getElementById('editor'), {
  mode: 'application/xml',
  theme: 'material-darker',
  lineNumbers: true,
  lineWrapping: false,
  value: INITIAL_EDITOR_VALUE
});

const fileInput = document.getElementById('file-input');
const statusBar = document.getElementById('status-bar');
const statusMessage = document.querySelector('.status-message');
const sidePanel = document.getElementById('side-panel');
const errorList = document.getElementById('error-list');
const additionalErrors = document.getElementById('additional-errors');
const summaryList = document.getElementById('summary-list');
const summaryStatus = document.getElementById('summary-status');
const sideSubtitle = document.getElementById('side-subtitle');
const htmlReport = document.getElementById('html-report');
const csvReport = document.getElementById('csv-report');

const HIGHLIGHT_DURATION_MS = 2000;
const REPORT_PATH_PREFIX = '/files/download/';
const THEME_LABELS = {
  dark: 'Light Mode',
  light: 'Dark Mode'
};

let currentHighlight = null;
let currentFileName = null;
let currentFileExtension = '.xml';

const ALLOWED_EXTENSIONS = ['.xml', '.csv'];

function setStatus(message, variant = '') {
  statusMessage.textContent = message;
  statusBar.classList.remove('error', 'success');
  if (variant) {
    statusBar.classList.add(variant);
  }
}

function getFileExtension(filename) {
  const match = filename ? filename.toLowerCase().match(/\.[^./\\]+$/) : null;
  return match ? match[0] : '';
}

function isAllowedExtension(extension) {
  return ALLOWED_EXTENSIONS.includes(extension);
}

function setCurrentFile(file) {
  if (!file) {
    currentFileName = null;
    currentFileExtension = '.xml';
    return;
  }
  currentFileName = file.name || 'editor.xml';
  const extension = getFileExtension(currentFileName) || '.xml';
  currentFileExtension = isAllowedExtension(extension) ? extension : '.xml';
}

function openFilePicker() {
  fileInput.value = '';
  fileInput.click();
}

function loadFile(file) {
  const reader = new FileReader();
  reader.onload = () => {
    editor.setValue(reader.result || '');
    setStatus(`Loaded ${file.name}`);
  };
  reader.readAsText(file);
}

function handleFileSelection(file) {
  if (!file) {
    return;
  }
  const extension = getFileExtension(file.name);
  if (!isAllowedExtension(extension)) {
    setCurrentFile(null);
    setStatus('Only XML or CSV files can be uploaded.', 'error');
    return;
  }
  setCurrentFile(file);
  loadFile(file);
}

function prettyPrintXml() {
  try {
    const xmlValue = editor.getValue();
    if (!xmlValue.trim()) {
      setStatus('Nothing to format.');
      return;
    }
    let formatted = formatXml(xmlValue);
    for (let i = 0; i < MAX_FORMAT_ITERATIONS; i += 1) {
      const next = formatXml(formatted);
      if (next === formatted) {
        break;
      }
      formatted = next;
    }
    editor.setValue(formatted);
    setStatus('XML formatted.');
  } catch (error) {
    setStatus('Pretty print failed: Invalid XML.', 'error');
  }
}

function formatXml(xml) {
  const parser = new DOMParser();
  const xmlDoc = parser.parseFromString(xml, 'application/xml');
  if (xmlDoc.querySelector('parsererror')) {
    throw new Error('Invalid XML');
  }

  stripWhitespaceNodes(xmlDoc);
  const serialized = new XMLSerializer().serializeToString(xmlDoc);
  const reg = /(>)(<)(\/*)/g;
  const normalized = serialized.replace(/>\s+</g, '><');
  const formatted = normalized.replace(reg, '$1\n$2$3');
  const lines = formatted.split('\n');
  let indent = 0;
  const pad = '  ';
  return lines
    .map((line) => {
      const trimmed = line.trim();
      if (!trimmed) {
        return '';
      }
      if (trimmed.match(/^<\//)) {
        indent = Math.max(indent - 1, 0);
      }
      const output = `${pad.repeat(indent)}${trimmed}`;
      if (trimmed.match(/^<[^!?][^>]*[^/]>/) && !trimmed.match(/<.*>.*<\//)) {
        indent += 1;
      }
      return output;
    })
    .filter((line) => line.length > 0)
    .join('\n');
}

async function validateXml() {
  setStatus('Validating...', '');
  const xmlContent = editor.getValue();
  const formData = new FormData();
  const extension = isAllowedExtension(currentFileExtension) ? currentFileExtension : '.xml';
  const safeName = currentFileName && isAllowedExtension(getFileExtension(currentFileName))
    ? currentFileName
    : `editor${extension}`;
  const mimeType = extension === '.csv' ? 'text/csv' : 'text/xml';
  const file = new File([xmlContent], safeName, { type: mimeType });
  formData.append('file', file);

  try {
    const response = await fetch('/files/validate', {
      method: 'POST',
      body: formData
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || data.error || 'Validation failed');
    }

    handleValidationResult(data);
  } catch (error) {
    setStatus(`Validation error: ${error.message}`, 'error');
  }
}

function handleValidationResult(data) {
  const lineErrors = data.errors?.line_errors || [];
  const additional = data.errors?.additional_error_details || [];
  const hasErrors = lineErrors.length > 0 || additional.length > 0;
  const apiStatus = data.status || '';
  const isPassed = apiStatus === 'PASSED' && !hasErrors;
  const displayStatus = isPassed ? 'PASSED' : 'FAILED';

  setStatus(`Validation ${displayStatus.toLowerCase()}.`, isPassed ? 'success' : 'error');
  updateReportLinks(data);
  renderSummary(data, summaryList, summaryStatus);
  renderErrors(data);
  sidePanel.classList.remove('hidden');
  sideSubtitle.textContent = hasErrors
    ? `${lineErrors.length + additional.length} issues detected.`
    : 'Validation passed.';
  switchTab(hasErrors ? 'errors' : 'summary');
}

function renderErrors(data) {
  errorList.innerHTML = '';
  additionalErrors.textContent = '';

  const lineErrors = data.errors?.line_errors || [];
  const additional = data.errors?.additional_error_details || [];

  if (!lineErrors.length) {
    const empty = document.createElement('div');
    empty.className = 'additional-errors';
    empty.textContent = 'No line-level errors returned.';
    errorList.appendChild(empty);
  }

  lineErrors.forEach((err) => {
    const lineNumber = Number.parseInt(
      err?.line_no ?? err?.line ?? err?.line_number ?? err?.lineNumber,
      10
    );
    const hasLineNumber = Number.isFinite(lineNumber);
    const message =
      err?.message ||
      err?.detail ||
      err?.error ||
      err?.description ||
      'Unknown validation error.';
    const item = document.createElement('li');
    item.className = 'error-item';
    item.innerHTML = `
      <div class="error-line">${hasLineNumber ? `Line ${lineNumber}` : 'Line details unavailable'}</div>
      <div class="error-message">${message}</div>
    `;
    if (hasLineNumber) {
      item.addEventListener('click', () => focusLine(lineNumber));
    }
    errorList.appendChild(item);
  });

  if (additional.length) {
    additionalErrors.textContent = additional
      .map((entry) => (typeof entry === 'string' ? entry : JSON.stringify(entry)))
      .join(' | ');
  }
}

function focusLine(lineNumber) {
  const line = Math.max(lineNumber - 1, 0);
  editor.focus();
  editor.setCursor({ line, ch: 0 });
  editor.scrollIntoView({ line, ch: 0 }, 80);

  if (currentHighlight) {
    editor.removeLineClass(currentHighlight, 'background', 'line-highlight');
  }
  currentHighlight = editor.addLineClass(line, 'background', 'line-highlight');
  setTimeout(() => {
    if (currentHighlight !== null) {
      editor.removeLineClass(currentHighlight, 'background', 'line-highlight');
      currentHighlight = null;
    }
  }, HIGHLIGHT_DURATION_MS);
}

function renderSummary(data, targetList, targetStatus) {
  targetList.innerHTML = '';
  const checks = data.checks || {};
  const entries = Object.entries(checks);

  targetStatus.textContent = `${data.filename || 'File'} • ${data.version || 'Unknown version'} • ${data.status || ''}`;

  if (!entries.length) {
    const item = document.createElement('li');
    item.className = 'summary-item';
    item.textContent = 'No checks returned.';
    targetList.appendChild(item);
    return;
  }

  entries.forEach(([label, value]) => {
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      const header = document.createElement('li');
      header.className = 'summary-item';
      header.innerHTML = `<span class="status-icon unknown">•</span><div>${label}</div>`;
      targetList.appendChild(header);
      Object.entries(value).forEach(([subLabel, subValue]) => {
        targetList.appendChild(buildSummaryItem(`${subLabel}`, subValue));
      });
    } else {
      targetList.appendChild(buildSummaryItem(label, value));
    }
  });
}

function buildSummaryItem(label, value) {
  const item = document.createElement('li');
  item.className = 'summary-item';
  const normalized =
    typeof value === 'string' ? value.trim().toLowerCase() : value;
  const boolValue = normalized === 'true' ? true : normalized === 'false' ? false : value;
  const status = boolValue === true ? 'success' : boolValue === false ? 'fail' : 'unknown';
  const icon = status === 'success' ? '✓' : status === 'fail' ? '✕' : '•';
  const detail = boolValue && typeof boolValue === 'object' ? JSON.stringify(boolValue) : '';
  item.innerHTML = `
    <span class="status-icon ${status}">${icon}</span>
    <div>
      <div>${label}</div>
      ${detail ? `<div class="summary-status">${detail}</div>` : ''}
    </div>
  `;
  return item;
}

function updateReportLinks(data) {
  setReportLink(htmlReport, data.html_report_url);
  setReportLink(csvReport, data.csv_report_url);
}

function setReportLink(anchor, path) {
  if (typeof path !== 'string' || !path.trim()) {
    anchor.removeAttribute('href');
    anchor.classList.add('disabled');
    anchor.setAttribute('aria-disabled', 'true');
    return;
  }
  let url;
  try {
    url = new URL(path, window.location.origin);
  } catch (error) {
    anchor.removeAttribute('href');
    anchor.classList.add('disabled');
    anchor.setAttribute('aria-disabled', 'true');
    return;
  }
  if (!['http:', 'https:'].includes(url.protocol) || !url.pathname.startsWith(REPORT_PATH_PREFIX)) {
    anchor.removeAttribute('href');
    anchor.classList.add('disabled');
    anchor.setAttribute('aria-disabled', 'true');
    return;
  }
  anchor.href = url.toString();
  anchor.classList.remove('disabled');
  anchor.removeAttribute('aria-disabled');
}

function downloadXml() {
  const blob = new Blob([editor.getValue()], { type: 'text/xml' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'document.xml';
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

function clearEditor() {
  editor.setValue('');
  setCurrentFile(null);
  setStatus('Editor cleared.');
}

function stripWhitespaceNodes(node) {
  const whitespaceNodes = [];
  Array.from(node.childNodes).forEach((child) => {
    if (child.nodeType === Node.TEXT_NODE && !child.nodeValue.trim()) {
      whitespaceNodes.push(child);
    } else if (child.nodeType === Node.ELEMENT_NODE) {
      stripWhitespaceNodes(child);
    }
  });
  whitespaceNodes.forEach((child) => child.parentNode.removeChild(child));
}

function applyTheme(theme) {
  document.body.dataset.theme = theme;
  editor.setOption('theme', theme === 'light' ? 'default' : 'material-darker');
  localStorage.setItem('validator-theme', theme);
  const toggle = document.getElementById('theme-toggle');
  if (toggle) {
    toggle.textContent = THEME_LABELS[theme] || 'Theme';
  }
  editor.refresh();
}

function adjustFontSize(delta) {
  const currentValue = getComputedStyle(document.documentElement).getPropertyValue('--editor-font-size').trim();
  const current = Number.parseFloat(currentValue.replace('px', ''));
  const next = Math.min(MAX_FONT_SIZE, Math.max(MIN_FONT_SIZE, current + delta));
  document.documentElement.style.setProperty('--editor-font-size', `${next}px`);
  localStorage.setItem('validator-font-size', `${next}`);
  editor.refresh();
}

function initializePreferences() {
  const storedTheme = localStorage.getItem('validator-theme') || DEFAULT_THEME;
  applyTheme(storedTheme);
  const storedFont = Number.parseInt(localStorage.getItem('validator-font-size'), 10);
  const fontSize = Number.isNaN(storedFont) ? DEFAULT_FONT_SIZE : storedFont;
  document.documentElement.style.setProperty('--editor-font-size', `${fontSize}px`);
}

function switchTab(tabName) {
  document.querySelectorAll('.tab-btn').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
  });
  document.querySelectorAll('.tab-panel').forEach((panel) => {
    panel.classList.toggle('active', panel.id.startsWith(tabName));
  });
}

fileInput.addEventListener('change', (event) => {
  const file = event.target.files[0];
  handleFileSelection(file);
});

function bindClick(id, handler) {
  const element = document.getElementById(id);
  if (element) {
    element.addEventListener('click', handler);
  }
}

bindClick('upload-btn', openFilePicker);
bindClick('pretty-btn', prettyPrintXml);
bindClick('validate-btn', validateXml);
bindClick('undo-btn', () => editor.undo());
bindClick('redo-btn', () => editor.redo());
bindClick('download-btn', downloadXml);
bindClick('clear-btn', clearEditor);
bindClick('font-decrease', () => adjustFontSize(-1));
bindClick('font-increase', () => adjustFontSize(1));
bindClick('theme-toggle', () => {
  const currentTheme = document.body.dataset.theme || DEFAULT_THEME;
  applyTheme(currentTheme === 'light' ? 'dark' : 'light');
});

document.querySelectorAll('.tab-btn').forEach((btn) => {
  btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

initializePreferences();
if (editor.getValue() !== INITIAL_EDITOR_VALUE) {
  editor.setValue(INITIAL_EDITOR_VALUE);
}
editor.clearHistory();
