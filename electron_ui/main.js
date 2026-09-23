const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const { spawn } = require('child_process');
const path = require('path');

const PROJECT_ROOT = path.join(__dirname, '..');
const PYTHON_BIN = path.join(PROJECT_ROOT, 'venv', 'bin', 'python');
const BACKEND_SCRIPT = path.join(PROJECT_ROOT, 'run.py');

let backendProcess = null;
let mainWindow = null;

function startBackend() {
  backendProcess = spawn(PYTHON_BIN, [BACKEND_SCRIPT], {
    cwd: PROJECT_ROOT,
  });

  backendProcess.stdout.on('data', (data) => {
    process.stdout.write(`[backend] ${data}`);
  });

  backendProcess.stderr.on('data', (data) => {
    process.stderr.write(`[backend] ${data}`);
  });

  backendProcess.on('error', (err) => {
    console.error('No se pudo arrancar el backend:', err.message);
  });

  backendProcess.on('exit', (code) => {
    console.log(`El backend terminó con código ${code}`);
    backendProcess = null;
  });
}

function stopBackend() {
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 980,
    height: 640,
    minWidth: 720,
    minHeight: 480,
    backgroundColor: '#14171C',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));
}

ipcMain.handle('elegir-carpeta', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory', 'createDirectory'],
  });
  if (result.canceled || result.filePaths.length === 0) return null;
  return result.filePaths[0];
});


app.whenReady().then(() => {
  startBackend();
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  stopBackend();
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', stopBackend);