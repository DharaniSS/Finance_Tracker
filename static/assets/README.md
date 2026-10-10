# Static assets

This directory is reserved for local images, icons, and other static files. The dashboard uses Plotly.js from its official CDN; deployments that must work offline should vendor a reviewed copy here and update the dashboard template.

Application state is served by Flask APIs. `static/js/app.js` keeps only transient API responses in memory; it does not seed or persist financial data in localStorage. CSV uploads are processed in memory and are not retained as files.