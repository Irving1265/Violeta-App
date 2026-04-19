from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired, FileAllowed
from wtforms import StringField, TextAreaField, PasswordField, SubmitField, HiddenField, BooleanField
from wtforms.validators import DataRequired, Length, EqualTo, ValidationError
import re

class EmailValidator:
    def __init__(self, message=None):
        self.message = message or 'Por favor ingresa un email válido.'
    
    def __call__(self, form, field):
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, field.data):
            raise ValidationError(self.message)

class LoginForm(FlaskForm):
    username = StringField('Usuario', validators=[DataRequired()])
    password = PasswordField('Contraseña', validators=[DataRequired()])
    submit = SubmitField('Iniciar Sesión')

class RegisterForm(FlaskForm):
    invite_code = StringField('Código de invitación', validators=[DataRequired(), Length(min=6, max=32)])
    username = StringField('Usuario', validators=[DataRequired(), Length(min=3, max=20)])
    email = StringField('Email', validators=[DataRequired(), EmailValidator()])
    password = PasswordField('Contraseña', validators=[DataRequired(), Length(min=6)])
    password2 = PasswordField('Confirmar Contraseña', validators=[DataRequired(), EqualTo('password')])
    eligibility_attestation = BooleanField('Declaro que soy mujer y que no estoy suplantando identidad.', validators=[DataRequired()])
    submit = SubmitField('Registrarse')

class PostForm(FlaskForm):
    caption = TextAreaField('Descripción', validators=[Length(max=500)])
    image = FileField('Imagen', validators=[
        FileRequired(),
        FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Solo se permiten imágenes')
    ])
    # Campos de geolocalización (ocultos, se llenan con JavaScript)
    latitude = HiddenField('Latitud')
    longitude = HiddenField('Longitud')
    location_name = StringField('Ubicación', validators=[Length(max=255)])
    city = StringField('Ciudad', validators=[Length(max=100)])
    country = StringField('País', validators=[Length(max=100)])
    submit = SubmitField('Publicar')

class CommentForm(FlaskForm):
    content = TextAreaField('Comentario', validators=[DataRequired(), Length(max=300)])
    submit = SubmitField('Comentar')

class ShareForm(FlaskForm):
    receiver_username = StringField('Usuario destinatario', validators=[DataRequired()])
    message = TextAreaField('Mensaje (opcional)', validators=[Length(max=200)])
    submit = SubmitField('Compartir')
