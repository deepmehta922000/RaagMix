const { contextBridge } = require('electron')

contextBridge.exposeInMainWorld('raagmix', {
  version: process.env.npm_package_version,
})
