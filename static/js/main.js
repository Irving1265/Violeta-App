document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.comment-form').forEach(form => {
        form.addEventListener('submit', async function(e) {
            e.preventDefault();

            const card = this.closest('.violeta-card');
            if (!card) return;
            const postId = card.dataset.postId;
            const input = this.querySelector('input[name="content"]');
            const content = (input?.value || '').trim();
            if (!content) return;

            // Construir headers con CSRF si está disponible (definido en app.js)
            const headers = typeof buildHeaders === 'function' ? buildHeaders('application/json') : { 'Content-Type': 'application/json', 'Accept': 'application/json' };

            try {
                const response = await fetch(`/comment/${postId}`, {
                    method: 'POST',
                    headers,
                    body: JSON.stringify({ content })
                });

                let data = null;
                try { data = await response.json(); } catch (_) {}

                if (!response.ok || !data || !data.ok) {
                    const message = (data && data.error) ? data.error : 'No se pudo enviar el comentario.';
                    if (typeof showAlert === 'function') {
                        showAlert(message, 'danger');
                    } else {
                        console.error(message);
                    }
                    return;
                }

                // Agregar el comentario a la lista según respuesta del backend
                const commentsList = card.querySelector('.comments-list');
                if (commentsList && data.comment) {
                    const newComment = document.createElement('div');
                    newComment.className = 'comment mb-2';
                    const badge = typeof renderAdminBadge === 'function' ? renderAdminBadge(data.comment.username, 'admin-badge--xs') : '';
                    newComment.innerHTML = `<strong>${data.comment.username}${badge}:</strong> ${data.comment.content}`;
                    commentsList.appendChild(newComment);
                }

                // Limpiar el input y quitar el mensaje de placeholder
                if (input) {
                    input.value = '';
                    input.placeholder = 'Escribir un comentario...';
                    input.blur();
                }
            } catch (error) {
                console.error('Error:', error);
                if (typeof showAlert === 'function') {
                    showAlert('Ocurrió un error al enviar tu comentario.', 'danger');
                }
            }
        });
    });
});
