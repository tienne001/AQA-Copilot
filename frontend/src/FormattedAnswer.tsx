import {memo,useState} from 'react';
import {inlineParts,parseAnswer} from './answer-format.mjs';
import './answer-format.css';

function Inline({text}:{text:string}){
  return <>{inlineParts(text).map((part,index)=>part.type==='code'?<code key={index}>{part.text}</code>:part.type==='strong'?<strong key={index}>{part.text}</strong>:part.type==='em'?<em key={index}>{part.text}</em>:<span key={index}>{part.text}</span>)}</>;
}

function CodeBlock({text,language,pending}:{text:string;language:string;pending:boolean}){
  const [copied,setCopied]=useState(false);
  const [error,setError]=useState('');
  const [wrap,setWrap]=useState(false);
  const copy=async()=>{
    setError('');
    try{
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(()=>setCopied(false),1800);
    }catch{setError('Не удалось скопировать. Выделите код и нажмите Ctrl+C.');}
  };
  return <section className="answer-code" aria-label={`Блок кода${language?' '+language:''}`}>
    <div className="answer-code-toolbar"><span>{language||'Код'}{pending?' · печатается…':''}</span><div>
      <button type="button" aria-pressed={wrap} onClick={()=>setWrap(v=>!v)}>Перенос строк</button>
      <button type="button" onClick={()=>void copy()}>{copied?'Скопировано':'Копировать код'}</button>
    </div></div>
    <pre className={wrap?'wrap':''} tabIndex={0}><code>{text}</code></pre>
    {error&&<div className="answer-copy-error" role="status">{error}</div>}
  </section>;
}

export const FormattedAnswer=memo(function FormattedAnswer({text,pending=false}:{text:string;pending?:boolean}){
  return <div className="formatted-answer">{parseAnswer(text).map((block,index)=>{
    switch(block.type){
      case 'code':return <CodeBlock key={index} text={block.text!} language={block.language!} pending={pending&&!block.closed}/>;
      case 'heading':return <div className="answer-heading" role="heading" aria-level={Math.min(block.level!+2,6)} key={index}><Inline text={block.text!}/></div>;
      case 'list':{const items=block.items!.map((item:string,j:number)=><li key={j}><Inline text={item}/></li>);return block.ordered?<ol key={index} start={block.start}>{items}</ol>:<ul key={index}>{items}</ul>;}
      case 'quote':return <blockquote key={index}><Inline text={block.text!}/></blockquote>;
      case 'table':return <div className="answer-table" key={index}><table><thead><tr>{block.header!.map((cell:string,j:number)=><th key={j}><Inline text={cell}/></th>)}</tr></thead><tbody>{block.rows!.map((row:string[],j:number)=><tr key={j}>{block.header!.map((_:string,k:number)=><td key={k}><Inline text={row[k]??''}/></td>)}</tr>)}</tbody></table></div>;
      default:return <p key={index}><Inline text={block.text!}/></p>;
    }
  })}</div>;
});
