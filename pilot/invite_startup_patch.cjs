// Apply only the invitation startup changes to an installed browser-login variant.
const fs=require('node:fs');
function patch(source){
 const marker='const tg=window.Telegram?.WebApp;';
 if(!source.includes(marker))throw Error('Unknown startup: refusing to modify');
 let fixed=source.includes(marker+'tg?.ready();')?source:source.replace(marker,marker+'tg?.ready();');
 fixed=fixed.replace('tg.ready();tg.expand();','tg.expand();');
 fixed=fixed.replace("{initData:tg.initData},15000)","{initData:tg.initData,...(new URLSearchParams(location.search).get('invite')?{invite:new URLSearchParams(location.search).get('invite')}:{})},15000)");
 return fixed;
}
module.exports=patch;
if(require.main===module){
 const path=process.argv[2];
 if(!path)throw Error('Pass the installed pilot.js path');
 const original=fs.readFileSync(path,'utf8'),fixed=patch(original);
 new (require('node:vm').Script)(fixed);
 fs.writeFileSync(path+'.before-invite-fix',original,{flag:'wx'});
 fs.writeFileSync(path+'.tmp',fixed);
 fs.renameSync(path+'.tmp',path);
 console.log('Startup patched; browser access preserved; backup saved.');
}
