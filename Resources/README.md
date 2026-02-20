# BA_Tools Shared Resources

This folder contains shared XAML resources used across all BA_Tools windows to maintain a consistent, modern UI.

## Files

### `BAWindowStyles.xaml`
Centralized ResourceDictionary containing all standard button styles and scrollbar styling used throughout the extension.

## Usage (pyRevit)

In pyRevit, **do not** reference `BAWindowStyles.xaml` from XAML (pack:// or relative paths fail because `Assembly.GetEntryAssembly()` returns null). Instead, merge the shared styles **in Python** after loading the window.

### 1. XAML

Do **not** add `ResourceDictionary.MergedDictionaries` or any `Source` to `BAWindowStyles.xaml` in your window XAML. Use only tool-specific styles in `Window.Resources`; the shared styles are merged in code.

```xml
<Window.Resources>
    <ResourceDictionary>
        <!-- Tool-specific styles only; shared BA styles merged in script -->
        <Style x:Key="DarkComboBox" ... />
    </ResourceDictionary>
</Window.Resources>
```

### 2. Python script (after loading the window)

After loading the window with `XamlReader.Load` (or `wpf.LoadComponent`), call the helper so shared styles (PrimaryButton, SecondaryButton, CloseButton, etc.) resolve:

```python
import os
import sys

# After: self._window = XamlReader.Load(stream.BaseStream)  (or equivalent)
script_dir = os.path.dirname(xaml_path)  # or os.path.dirname(__file__), PATH_SCRIPT, etc.
_root = script_dir
for _ in range(15):
    _root = os.path.dirname(_root)
    if not _root or os.path.isfile(os.path.join(_root, "Resources", "BAWindowStyles.xaml")):
        break
if _root and _root not in sys.path:
    sys.path.insert(0, _root)
import ba_ui_helper
ba_ui_helper.merge_ba_window_styles(self._window, script_dir)  # use self for wpf.LoadComponent
```

The extension root contains `ba_ui_helper.py`, which provides `merge_ba_window_styles(window, script_dir)`.

## Available Styles

### Button Styles

| Style Key | Description | Usage |
|-----------|-------------|-------|
| `PrimaryButton` | Blue solid button for primary actions | `<Button Style="{StaticResource PrimaryButton}">` |
| `SecondaryButton` | Dark button with blue outline for secondary actions | `<Button Style="{StaticResource SecondaryButton}">` |
| `CloseButton` | Standardized close button (70×32px) | `<Button x:Name="btnClose" Style="{StaticResource CloseButton}">` |
| `ModernButton` | Alias for PrimaryButton (backward compatibility) | `<Button Style="{StaticResource ModernButton}">` |

### Scrollbar Styles

Automatically applied to all `ScrollBar` and `ScrollViewer` elements:
- Slim 5px width scrollbar
- Dark background (`#0A0A12`)
- Transparent ScrollViewer background

## Style Properties

### PrimaryButton
- **Background:** `#1976D2` (Blue)
- **Hover:** `#2196F3` (Lighter blue)
- **Disabled:** `#1C1C2C` (Dark gray)
- **Corner Radius:** 6px
- **Font:** Segoe UI, 12pt, SemiBold

### SecondaryButton
- **Background:** `#1A1A2A` (Dark)
- **Border:** `#1976D2` (Blue), 0.8px
- **Hover:** Background `#22223A`, Border `#2196F3`, Text White
- **Corner Radius:** 6px
- **Font:** Segoe UI, 12pt, SemiBold

### CloseButton
- **Size:** 70×32px (fixed)
- **Background:** `#1A1A2A` (Dark)
- **Border:** `#1976D2` (Blue), 0.8px
- **Hover:** Background `#1976D2`, Border `#2196F3`, Text White
- **Corner Radius:** 6px
- **Font:** Segoe UI, 12pt, SemiBold

## Standard Window Structure

All BA_Tools windows should follow this structure:

```xml
<Window WindowStyle="None"
        AllowsTransparency="True"
        Background="Transparent"
        ...>
    
    <Window.Resources>
        <!-- Merge shared styles -->
        <ResourceDictionary>
            <ResourceDictionary.MergedDictionaries>
                <ResourceDictionary Source="pack://application:,,,/BA_Tools.extension;component/Resources/BAWindowStyles.xaml"/>
            </ResourceDictionary.MergedDictionaries>
        </ResourceDictionary>
    </Window.Resources>
    
    <!-- Outer shell -->
    <Border Background="#0A0A12" CornerRadius="12">
        <Grid>
            <Grid.RowDefinitions>
                <RowDefinition Height="58"/>  <!-- Title bar -->
                <RowDefinition Height="26"/>  <!-- Subtitle (optional) -->
                <RowDefinition Height="*"/>   <!-- Content -->
                <RowDefinition Height="64"/>  <!-- Footer -->
            </Grid.RowDefinitions>
            
            <!-- Row 0: Title bar with BA badge, title, close button -->
            <!-- Row 1: Optional subtitle -->
            <!-- Row 2: Scrollable main content -->
            <!-- Row 3: Footer with status and action buttons -->
        </Grid>
    </Border>
</Window>
```

## Color Palette

| Color | Hex | Usage |
|-------|-----|-------|
| Primary Blue | `#1976D2` | Primary buttons, borders, accents |
| Hover Blue | `#2196F3` | Button hover states |
| Dark Background | `#0A0A12` | Window background |
| Card Background | `#0E0E1A` | Content cards, header, footer |
| Button Dark | `#1A1A2A` | Secondary button background |
| Text Primary | `White` | Primary text |
| Text Secondary | `#A0A0C0` | Secondary text |
| Text Info | `#FFCDA2` | Informational text (subtitles, hints) |

## Best Practices

1. **Always merge the ResourceDictionary** - Don't copy styles into individual files
2. **Use style keys** - Reference styles by key: `Style="{StaticResource PrimaryButton}"`
3. **Keep tool-specific styles separate** - Add custom styles after merging shared resources
4. **Maintain consistency** - Use PrimaryButton for main actions, SecondaryButton for secondary actions
5. **Preserve control names** - Keep all `x:Name` attributes for script compatibility

## Troubleshooting

### Styles not loading
- Verify the path to `BAWindowStyles.xaml` is correct relative to your XAML file
- Check that the ResourceDictionary is properly merged
- Ensure the XAML file is included in your extension build

### Styles not applying
- Make sure you're using `StaticResource` (not `DynamicResource`)
- Verify the style key name matches exactly (case-sensitive)
- Check that the ResourceDictionary merge is inside `Window.Resources`

### ResourceDictionary loading errors
- **Error:** `Assembly.GetEntryAssembly() returns null` or `XamlParseException` when loading ResourceDictionary
- **Solution:** Use the pack URI syntax: `pack://application:,,,/BA_Tools.extension;component/Resources/BAWindowStyles.xaml`
- Relative paths (`../../../../`) do not work in pyRevit because the entry assembly cannot be determined

## Maintenance

When updating shared styles:
1. Edit `BAWindowStyles.xaml` only
2. Changes automatically apply to all windows using the ResourceDictionary
3. Test across multiple tools to ensure consistency
4. Document any breaking changes or new styles added

## Version History

- **v1.0** (2026-02-18): Initial release with PrimaryButton, SecondaryButton, CloseButton, and scrollbar styles
