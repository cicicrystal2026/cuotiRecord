const path=require('path'),os=require('os');
function playwright(){for(const root of [process.env.CUOTI_NODE_MODULES,path.join(os.homedir(),'AppData/Local/CuotiRecord/node/node_modules'),path.resolve(__dirname,'../node_modules'),path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules')].filter(Boolean)){try{return require(path.join(root,'playwright'));}catch{}}throw Error('Install Playwright with scripts/setup.ps1 or npm ci.');}
function browserPath(){return [process.env.CUOTI_BROWSER,'C:/Program Files/Google/Chrome/Application/chrome.exe','C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(p=>p&&require('fs').existsSync(p));}
module.exports={playwright,browserPath};
