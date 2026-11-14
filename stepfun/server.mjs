import express from 'express';
import {SeekdbClient, Schema, VectorIndexConfig, FulltextIndexConfig} from 'seekdb';
import {createServer} from 'vite';
import {performance} from 'node:perf_hooks';
const app=express(); app.use(express.json({limit:'8mb'}));
const db=new SeekdbClient(process.env.SEEKDB_HOST ? {host:process.env.SEEKDB_HOST,port:Number(process.env.SEEKDB_PORT||2881),user:process.env.SEEKDB_USER||'root',password:process.env.SEEKDB_PASSWORD||'',database:process.env.SEEKDB_DATABASE||'test'} : {path:process.env.SEEKDB_PATH||'./seekdb-data',database:'test'});
const queues=new Map();
const valid=(x)=>typeof x==='string'&&/^[a-z0-9_]{1,40}$/.test(x);
const vector=(x)=>Array.isArray(x)&&x.length===384&&x.every(Number.isFinite);
async function collection(name){if(!valid(name))throw Error('知识库标识非法');return db.getOrCreateCollection({name:'pocket_'+name,schema:new Schema({fulltextIndex:new FulltextIndexConfig('space'),vectorIndex:new VectorIndexConfig({hnsw:{dimension:384,distance:'cosine'},embeddingFunction:null})})});}
function serial(key,fn){const next=(queues.get(key)||Promise.resolve()).catch(()=>{}).then(fn);queues.set(key,next);return next.finally(()=>{if(queues.get(key)===next)queues.delete(key)});}
const route=(fn)=>(req,res)=>Promise.resolve(fn(req,res)).catch(e=>res.status(400).json({error:e.message}));
app.get('/api/health',route(async(req,res)=>res.json({database:await db.execute('SELECT VERSION() AS version')})));
app.post('/api/import',route(async(req,res)=>{const {kb,items,refresh=true}=req.body;if(!Array.isArray(items)||!items.length||items.length>64)throw Error('每次导入 1—64 段');for(const x of items)if(!vector(x.embedding)||typeof x.text!=='string'||x.text.length>3000||typeof x.id!=='string')throw Error('非法文档或向量');await serial(kb,async()=>{const c=await collection(kb);let t=performance.now();await c.upsert({ids:items.map(x=>x.id),documents:items.map(x=>x.text),embeddings:items.map(x=>x.embedding),metadatas:items.map(x=>({source:String(x.source).slice(0,200)}))});const writeMs=performance.now()-t;t=performance.now();if(refresh)await c.refresh_index();res.json({writeMs,refreshMs:performance.now()-t,count:items.length,refreshed:refresh})})}));
app.post('/api/refresh',route(async(req,res)=>{await serial(req.body.kb,async()=>{const c=await collection(req.body.kb),t=performance.now();await c.refresh_index();res.json({refreshMs:performance.now()-t})})}));
app.post('/api/search',route(async(req,res)=>{const {kb,query,embedding}=req.body;if(!vector(embedding)||typeof query!=='string'||!query.trim()||query.length>1000)throw Error('非法查询');await serial(kb,async()=>{const c=await collection(kb),t=performance.now();const result=await c.hybridSearch({query:{whereDocument:{$contains:query},nResults:20},knn:{queryEmbeddings:[embedding],nResults:20},rank:{rrf:{rankWindowSize:20,rankConstant:60}},nResults:5,include:['documents','metadatas','distances']});res.json({result,searchMs:performance.now()-t})})}));
const vite=await createServer({server:{middlewareMode:true},appType:'spa'});app.use(vite.middlewares);app.listen(5173,'127.0.0.1',()=>console.log('Pocket Seek http://localhost:5173'));
