document.querySelectorAll('button[data-copy]').forEach(button => {
  button.addEventListener('click', async () => {
    const status = button.nextElementSibling;
    try {
      await navigator.clipboard.writeText(document.getElementById(button.dataset.copy).textContent);
      status.textContent = 'Copied';
    } catch {
      status.textContent = 'Select the text above and copy it.';
    }
  });
});
