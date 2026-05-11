const editor = CodeMirror(document.getElementById('editor'), {
  mode: 'application/xml',
  theme: 'material-darker',
  lineNumbers: true,
  lineWrapping: false,
  value: '<Document>\n  <CstmrCdtTrfInitn>\n    <NbOfTxs>1</NbOfTxs>\n    <CtrlSum>0.00</CtrlSum>\n  </CstmrCdtTrfInitn>\n</Document>'
});

const fileInput = document.getElementById('file-input');
const statusBar = document.getElementById('status-bar');
const sidePanel = document.getElementById('side-panel');
const errorList = document.getElementById('error-list');
const additionalErrors = document.getElementById('additional-errors');
const summaryList = document.getElementById('summary-list');
const summaryStatus = document.getElementById('summary-status');
const sideSubtitle = document.getElementById('side-subtitle');
const htmlReport = document.getElementById('html-report');
const csvReport = document.getElementById('csv-report');
const summaryModal = document.getElementById('summary-modal');
const modalSummaryList = document.getElementById('modal-summary-list');
const modalStatus = document.getElementById('modal-status');
const modalHtmlReport = document.getElementById('modal-html-report');
const modalCsvReport = document.getElementById('modal-csv-report');

let currentHighlight = null;

function setStatus(message, variant = '') {
  statusBar.textContent = message;
  statusBar.dataset.variant = variant;
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

function prettyPrintXml() {
  try {
    const formatted = formatXml(editor.getValue());
    editor.setValue(formatted);
    setStatus('XML formatted.');
  } catch (error) {
    setStatus('Pretty print failed: Invalid XML.');
    alert('Unable to format XML. Please ensure the XML is valid.');
  }
}

function formatXml(xml) {
  const parser = new DOMParser();
  const xmlDoc = parser.parseFromString(xml, 'application/xml');
  if (xmlDoc.querySelector('parsererror')) {
    throw new Error('Invalid XML');
  }

  const serialized = new XMLSerializer().serializeToString(xmlDoc);
  const reg = /(>)(<)(\/*)/g;
  const formatted = serialized.replace(reg, '$1\n$2$3');
  const lines = formatted.split('\n');
  let indent = 0;
  const pad = '  ';
  return lines
    .map((line) => {
      if (line.match(/^<\//)) {
        indent = Math.max(indent - 1, 0);
      }
      const output = `${pad.repeat(indent)}${line}`;
      if (line.match(/^<[^!?][^>]*[^/]>/) && !line.match(/<.*>.*<\//)) {
        indent += 1;
      }
      return output;
    })
    .join('\n');
}

async function validateXml() {
  setStatus('Validating...');
  const xmlContent = editor.getValue();
  const formData = new FormData();
  const file = new File([xmlContent], 'editor.xml', { type: 'text/xml' });
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
    setStatus(`Validation error: ${error.message}`);
  }
}

function handleValidationResult(data) {
  const status = data.status || 'FAILED';
  const isPassed = status === 'PASSED';

  setStatus(`Validation ${status.toLowerCase()}.`);
  updateReportLinks(data);
  renderSummary(data, summaryList, summaryStatus);
  renderSummary(data, modalSummaryList, modalStatus);

  if (isPassed) {
    sidePanel.classList.add('hidden');
    sideSubtitle.textContent = 'Validation passed.';
    showModal();
  } else {
    sidePanel.classList.remove('hidden');
    sideSubtitle.textContent = `${data.errors?.line_errors?.length || 0} issues detected.`;
    renderErrors(data);
  }
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
    const item = document.createElement('li');
    item.className = 'error-item';
    item.innerHTML = `
      <div class="error-line">Line ${err.line_no}</div>
      <div class="error-message">${err.message}</div>
    `;
    item.addEventListener('click', () => focusLine(err.line_no));
    errorList.appendChild(item);
  });

  if (additional.length) {
    additionalErrors.textContent = additional.join(' | ');
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
  }, 2000);
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
  const status = value === true ? 'success' : value === false ? 'fail' : 'unknown';
  const icon = status === 'success' ? '✓' : status === 'fail' ? '✕' : '•';
  const detail = value && typeof value === 'object' ? JSON.stringify(value) : '';
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
  const htmlUrl = new URL(data.html_report_url || '#', window.location.origin).toString();
  const csvUrl = new URL(data.csv_report_url || '#', window.location.origin).toString();
  htmlReport.href = htmlUrl;
  csvReport.href = csvUrl;
  modalHtmlReport.href = htmlUrl;
  modalCsvReport.href = csvUrl;
}

function showModal() {
  summaryModal.classList.remove('hidden');
}

function hideModal() {
  summaryModal.classList.add('hidden');
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

function switchTab(tabName) {
  document.querySelectorAll('.tab-btn').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
  });
  document.querySelectorAll('.tab-panel').forEach((panel) => {
    panel.classList.toggle('active', panel.id.startsWith(tabName));
  });
}

function togglePanel() {
  sidePanel.classList.toggle('collapsed');
  const icon = document.getElementById('collapse-icon');
  icon.textContent = sidePanel.classList.contains('collapsed') ? '⟩' : '⟨';
}

fileInput.addEventListener('change', (event) => {
  const file = event.target.files[0];
  if (file) {
    loadFile(file);
  }
});

document.getElementById('upload-btn').addEventListener('click', openFilePicker);
document.getElementById('pretty-btn').addEventListener('click', prettyPrintXml);
document.getElementById('validate-btn').addEventListener('click', validateXml);
document.getElementById('undo-btn').addEventListener('click', () => editor.undo());
document.getElementById('redo-btn').addEventListener('click', () => editor.redo());
document.getElementById('download-btn').addEventListener('click', downloadXml);
document.getElementById('close-modal').addEventListener('click', hideModal);
document.getElementById('collapse-btn').addEventListener('click', togglePanel);

summaryModal.addEventListener('click', (event) => {
  if (event.target === summaryModal) {
    hideModal();
  }
});

document.querySelectorAll('.tab-btn').forEach((btn) => {
  btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});
