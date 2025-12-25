
    document.addEventListener('DOMContentLoaded', function() {
        const form = document.querySelector('form[action="/form_builder/submit"]');
        
        if (form) {
            form.setAttribute('autocomplete', 'off');
            
            if (performance.navigation.type === 2) {
                form.reset();
                
                const fileInputs = form.querySelectorAll('input[type="file"]');
                fileInputs.forEach(input => {
                    input.value = '';
                    const preview = input.parentElement.querySelector('.file-preview');
                    if (preview) preview.innerHTML = '';
                });
                
                const checkboxes = form.querySelectorAll('input[type="checkbox"]');
                checkboxes.forEach(cb => cb.checked = false);
                
                const radios = form.querySelectorAll('input[type="radio"]');
                radios.forEach(radio => radio.checked = false);
                
                const textareas = form.querySelectorAll('textarea');
                textareas.forEach(textarea => textarea.value = '');
                
                const selects = form.querySelectorAll('select');
                selects.forEach(select => select.selectedIndex = 0);
                
                const ratingStars = form.querySelectorAll('.rating-star');
                ratingStars.forEach(star => star.classList.remove('active'));
                
                console.log('Form cleared after navigation');
            }
            
            form.addEventListener('submit', function(e) {
                sessionStorage.setItem('formSubmitted', 'true');
            });
        }
        
        if (sessionStorage.getItem('formSubmitted') === 'true') {
            sessionStorage.removeItem('formSubmitted');
            
            if (form) {
                form.reset();
                console.log('Form cleared after successful submission');
            }
        }
        
        window.addEventListener('beforeunload', function() {
            if (form && !form.hasAttribute('data-submitting')) {
                sessionStorage.removeItem('formSubmitted');
            }
        });
        
        if (form) {
            form.addEventListener('submit', function() {
                form.setAttribute('data-submitting', 'true');
            });
        }
    });
    
    window.addEventListener('focus', function() {
        const form = document.querySelector('form[action="/form_builder/submit"]');
        if (form && sessionStorage.getItem('formSubmitted') === 'true') {
            form.reset();
            sessionStorage.removeItem('formSubmitted');
        }
    });