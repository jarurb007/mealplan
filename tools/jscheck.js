const fs = require('fs');
const h = fs.readFileSync('/home/jar/mealplan/app/static/index.html', 'utf8');
const blocks = [...h.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
let bad = false;
blocks.forEach((b, i) => {
  try { new Function(b); console.log(`skrypt ${i + 1}: składnia ok (${b.length} znaków)`); }
  catch (e) { console.log(`skrypt ${i + 1}: BŁĄD SKŁADNI: ${e.message}`); bad = true; }
});
process.exit(bad ? 1 : 0);
