// De momento la interfaz solo necesita fetch() y WebSocket, ambas
// disponibles de forma nativa en el proceso de renderizado sin
// necesidad de exponer nada de Node. Este archivo queda preparado
// para el día que haga falta exponer algo (por ejemplo, un selector
// de carpeta de destino) a través de contextBridge.