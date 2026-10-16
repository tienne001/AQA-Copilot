import test from 'node:test';
import assert from 'node:assert/strict';
import {parseAnswer,inlineParts} from '../src/answer-format.mjs';

test('fenced code preserves indentation, blank lines, tabs and HTML literally',()=>{
  const code='async function run() {\n\tconst s = "<script>**not bold**</script>";\n\n  return s;\n}\n';
  const blocks=parseAnswer('Пример:\n\n```typescript\n'+code+'```\n\nКонец.');
  assert.equal(blocks[1].type,'code');assert.equal(blocks[1].language,'typescript');
  assert.equal(blocks[1].text,code);assert.equal(blocks[1].closed,true);
  assert.equal(blocks[2].text,'Конец.');
});
test('an unfinished fence remains a readable code block while streaming',()=>{
  for(const text of ['```js\nconst a =','```js\nconst a = 1;\n']){
    const block=parseAnswer(text)[0];assert.equal(block.type,'code');assert.equal(block.closed,false);
    assert.equal(block.text,text.slice(6));
  }
});
test('a shorter fence inside a longer fence does not close the block',()=>{
  const block=parseAnswer('````md\n```js\nlet a = 1;\n```\n````')[0];
  assert.equal(block.text,'```js\nlet a = 1;\n```\n');assert.equal(block.closed,true);
});
test('headings, ordered lists, bullet lists, paragraphs and quotes stay separate',()=>{
  const blocks=parseAnswer('## Ответ\n\nПервый абзац.\nПродолжение.\n\n- **Суть**\n- `await`\n\n3. Шаг\n4. Ещё шаг\n\n> Условие');
  assert.deepEqual(blocks.map(b=>b.type),['heading','paragraph','list','list','quote']);
  assert.equal(blocks[2].ordered,false);assert.equal(blocks[3].start,3);
});
test('inline code is not interpreted as emphasis or HTML',()=>{
  assert.deepEqual(inlineParts('Текст `**x** <img>` и **важно**.'),[
    {type:'text',text:'Текст '},{type:'code',text:'**x** <img>'},{type:'text',text:' и '},{type:'strong',text:'важно'},{type:'text',text:'.'},
  ]);
});
test('table columns and escaped pipes are retained',()=>{
  const block=parseAnswer('| Метод | Значение |\n| --- | --- |\n| `x` | a\\|b |')[0];
  assert.equal(block.type,'table');assert.deepEqual(block.rows,[['`x`','a|b']]);
});
test('raw HTML and unsafe markdown links stay literal text',()=>{
  const text='<img src=x onerror=alert(1)> [x](javascript:alert(1))';
  assert.equal(parseAnswer(text)[0].text,text);
  assert.deepEqual(inlineParts(text),[{type:'text',text}]);
});
