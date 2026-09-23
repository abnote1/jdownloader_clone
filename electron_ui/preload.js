const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  elegirCarpeta: () => ipcRenderer.invoke('elegir-carpeta'),
});