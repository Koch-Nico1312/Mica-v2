$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
$speaker.SelectVoice('Microsoft Hedda Desktop')
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$phrases = @('Was steht heute an?', 'Starte Ablauf Schulmodus', "Antworte bei technischen Fragen k$([char]0xfc)rzer", "Mach dort weiter, wo wir aufgeh$([char]0xf6)rt haben")
for ($index = 0; $index -lt $phrases.Count; $index++) {
    $speaker.SetOutputToWaveFile((Join-Path $PSScriptRoot "voice-$index.wav"), $format)
    $speaker.Speak($phrases[$index])
}
$speaker.Dispose()
