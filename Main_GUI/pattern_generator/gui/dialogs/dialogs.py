from datetime import datetime
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
                           QGroupBox, QLabel, QLineEdit, QTextEdit, QPushButton)

class SavePatternDialog(QDialog):
    """Dialog pour sauvegarder un pattern"""
    
    def __init__(self, current_config, parent=None):
        super().__init__(parent)
        self.current_config = current_config
        self.setWindowTitle("Save Pattern Configuration")
        self.setModal(True)
        self.resize(400, 300)
        
        layout = QVBoxLayout(self)
        
        # Nom du pattern
        form_layout = QFormLayout()
        self.nameEdit = QLineEdit()
        self.nameEdit.setPlaceholderText("Enter pattern name...")
        form_layout.addRow("Pattern Name:", self.nameEdit)
        
        self.descriptionEdit = QTextEdit()
        self.descriptionEdit.setPlaceholderText("Optional description...")
        self.descriptionEdit.setMaximumHeight(80)
        form_layout.addRow("Description:", self.descriptionEdit)
        
        layout.addLayout(form_layout)
        
        # Aperçu de la configuration
        preview_group = QGroupBox("Configuration Preview")
        preview_layout = QVBoxLayout(preview_group)
        
        self.previewText = QTextEdit()
        self.previewText.setReadOnly(True)
        self.previewText.setMaximumHeight(120)
        self._update_preview()
        preview_layout.addWidget(self.previewText)
        
        layout.addWidget(preview_group)
        
        # Boutons
        button_layout = QHBoxLayout()
        self.cancelButton = QPushButton("Cancel")
        self.cancelButton.clicked.connect(self.reject)
        self.saveButton = QPushButton("Save")
        self.saveButton.clicked.connect(self.accept)
        
        button_layout.addWidget(self.cancelButton)
        button_layout.addWidget(self.saveButton)
        layout.addLayout(button_layout)
        
        # Validation
        self.nameEdit.textChanged.connect(self._validate_input)
        self._validate_input()
    
    def _update_preview(self):
        """Mettre à jour l'aperçu de la configuration"""
        config_text = f"Pattern Type: {self.current_config.get('pattern_type', 'N/A')}\n"
        config_text += f"Actuators: {self.current_config.get('actuators', [])}\n"
        config_text += f"Intensity: {self.current_config.get('intensity', 0)}\n"
        config_text += f"Frequency: {self.current_config.get('frequency', 0)}\n"
        wd = self.current_config.get('waveform_duration', None)
        if wd is not None:
            config_text += f"Waveform Duration: {wd:.2f}s\n"
        
        # Waveform info
        waveform_info = self.current_config.get('waveform', {})
        if waveform_info:
            config_text += f"Waveform: {waveform_info.get('name', 'N/A')} ({waveform_info.get('source', 'N/A')})\n"
        
        # Paramètres spécifiques
        specific_params = self.current_config.get('specific_parameters', {})
        if specific_params:
            config_text += "Specific Parameters:\n"
            for key, value in specific_params.items():
                config_text += f"  {key}: {value}\n"
        
        self.previewText.setPlainText(config_text)
    
    def _validate_input(self):
        """Valider l'entrée utilisateur"""
        name = self.nameEdit.text().strip()
        self.saveButton.setEnabled(len(name) > 0)
    
    def get_save_data(self):
        """Récupérer les données de sauvegarde"""
        return {
            'name': self.nameEdit.text().strip(),
            'description': self.descriptionEdit.toPlainText().strip(),
            'timestamp': datetime.now().isoformat(),
            'config': self.current_config
        }
