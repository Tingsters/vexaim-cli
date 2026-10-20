document.getElementById('copy').addEventListener('click', async () => {
  const status = document.getElementById('copy-status');
  try {
    await navigator.clipboard.writeText(document.getElementById('prompt').textContent);
    status.textContent = 'Copied';
  } catch {
    status.textContent = 'Select the prompt text and copy it.';
  }
});
