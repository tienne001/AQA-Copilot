// Small, streaming-tolerant Markdown subset. Raw HTML is always literal text.
const fence = line => /^ {0,3}(`{3,}|~{3,})([^\n]*)$/.exec(line);
const listItem = line => /^ {0,3}(?:([-+*])|(\d+)[.)])\s+(.+)$/.exec(line);
const heading = line => /^ {0,3}(#{1,6})\s+(.+?)(?:\s+#+)?$/.exec(line);
const divider = line => /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
const cells = line => line.trim().replace(/^\|/, '').replace(/\|$/, '').split(/(?<!\\)\|/).map(s=>s.trim().replace(/\\\|/g,'|'));
const startsBlock = line => fence(line) || listItem(line) || heading(line) || /^\s*>/.test(line) || /^(?: {4}|\t)/.test(line);

export function parseAnswer(text) {
  const lines=text.replace(/\r\n?/g,'\n').split('\n');
  const blocks=[];
  let i=0;
  while(i<lines.length){
    if(!lines[i].trim()){i++;continue;}
    const open=fence(lines[i]);
    if(open){
      const body=[];const marker=open[1];i++;
      const close=new RegExp('^ {0,3}'+marker[0]+'{'+marker.length+',}\\s*$');
      while(i<lines.length&&!close.test(lines[i]))body.push(lines[i++]);
      const closed=i<lines.length;
      blocks.push({type:'code',language:(open[2].trim().match(/^[\w+#.-]{1,32}/)||[''])[0],text:body.join('\n')+(closed&&body.length?'\n':''),closed});
      if(closed)i++;
      continue;
    }
    if(/^(?: {4}|\t)/.test(lines[i])){
      const body=[];
      while(i<lines.length&&(/^(?: {4}|\t)/.test(lines[i])||!lines[i].trim()))body.push(lines[i++].replace(/^(?: {4}|\t)/,''));
      blocks.push({type:'code',language:'',text:body.join('\n'),closed:true});continue;
    }
    const h=heading(lines[i]);
    if(h){blocks.push({type:'heading',level:h[1].length,text:h[2]});i++;continue;}
    if(i+1<lines.length&&lines[i].includes('|')&&divider(lines[i+1])){
      const header=cells(lines[i]);i+=2;const rows=[];
      while(i<lines.length&&lines[i].trim()&&lines[i].includes('|'))rows.push(cells(lines[i++]));
      blocks.push({type:'table',header,rows});continue;
    }
    const item=listItem(lines[i]);
    if(item){
      const ordered=Boolean(item[2]);const items=[];const start=ordered?Number(item[2]):1;
      while(i<lines.length){
        const next=listItem(lines[i]);
        if(!next||Boolean(next[2])!==ordered)break;
        let value=next[3];i++;
        while(i<lines.length&&/^\s{2,}\S/.test(lines[i])&&!listItem(lines[i])&&!fence(lines[i]))value+='\n'+lines[i++].trim();
        items.push(value);
      }
      blocks.push({type:'list',ordered,start,items});continue;
    }
    if(/^\s*>/.test(lines[i])){
      const body=[];
      while(i<lines.length&&/^\s*>/.test(lines[i]))body.push(lines[i++].replace(/^\s*>\s?/,''));
      blocks.push({type:'quote',text:body.join('\n')});continue;
    }
    const body=[lines[i++]];
    while(i<lines.length&&lines[i].trim()&&!startsBlock(lines[i])&&!(i+1<lines.length&&divider(lines[i+1])))body.push(lines[i++]);
    blocks.push({type:'paragraph',text:body.join('\n')});
  }
  return blocks;
}

export function inlineParts(text){
  const result=[];
  const pattern=/(`+)([\s\S]*?)\1|\*\*([^*\n]+)\*\*|__([^_\n]+)__|\*([^*\n]+)\*/g;
  let end=0;
  for(const match of text.matchAll(pattern)){
    if(match.index>end)result.push({type:'text',text:text.slice(end,match.index)});
    result.push({type:match[1]?'code':match[3]||match[4]?'strong':'em',text:match[1]?match[2]:match[3]||match[4]||match[5]});
    end=match.index+match[0].length;
  }
  if(end<text.length)result.push({type:'text',text:text.slice(end)});
  return result;
}
