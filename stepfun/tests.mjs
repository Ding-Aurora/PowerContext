import test from 'node:test';import assert from 'node:assert/strict';import {chunks,recall} from './shared.js';
test('chunk overlap and empty input',()=>{assert.deepEqual(chunks(''),[]);const c=chunks(Array.from({length:300},(_,i)=>'w'+i).join(' '));assert.equal(c.length,3);assert.ok(c[1].startsWith('w120 '))});
test('recall truncates to K',()=>{assert.equal(recall(['a','b'],['b'],1),0);assert.equal(recall(['a','b'],['b']),1)});
